from unittest.mock import Mock, patch
from test_support import IsolatedSafetyTestCase
import computer_observation
import permissions
import safety
import capability_registry


class ObservationTests(IsolatedSafetyTestCase):
    def test_unnamed_scroll_pane_keeps_real_name_identity_and_can_be_located(self):
        from types import SimpleNamespace
        def element(runtime,name,kind,scrollable=False):
            return SimpleNamespace(CurrentIsPassword=False,CurrentName=name,CurrentControlType=kind,
                CurrentProcessId=2,CurrentIsEnabled=True,CurrentIsOffscreen=False,
                CurrentBoundingRectangle=SimpleNamespace(left=1,top=2,right=30,bottom=40),
                GetRuntimeId=lambda:runtime,GetCurrentPropertyValue=lambda prop:scrollable if prop==30034 else False)
        root=element((1,),'Spotify',50032)
        pane=element((2,),'',50026,True)
        ignored=element((3,),'',50026)
        automation=Mock(); automation.ElementFromHandle.return_value=root
        walker=automation.ControlViewWalker
        walker.GetFirstChildElement.side_effect=lambda item:pane if item is root else None
        walker.GetNextSiblingElement.side_effect=lambda item:ignored if item is pane else None
        with patch.object(computer_observation,'select_window',return_value=(1,2,'Spotify',4)), \
             patch.object(computer_observation,'automation_client',return_value=automation):
            snapshot=computer_observation.observe('Spotify')
            self.assertEqual(len(snapshot['controls']),2,'Unusable unnamed controls stay omitted')
            control=snapshot['controls'][1]
            self.assertEqual(control['name'],'','UI captions must not replace the provider name')
            self.assertTrue(control['scrollable'])
            self.assertIsNotNone(control['context_id'])
            fresh,located=computer_observation.observe('Spotify',locate=control['id'])
            self.assertIs(located[-1],pane)
            self.assertEqual(fresh['controls'][1],control)

    def context_chain(self):
        from types import SimpleNamespace
        def element(runtime,name,kind):
            return SimpleNamespace(CurrentIsPassword=False,CurrentName=name,CurrentControlType=kind,
                                   GetRuntimeId=lambda:runtime)
        root=element((1,),'Spotify',50032)
        document=element((2,),'Home',50030)
        button=element((3,),'Next',50000)
        walker=Mock()
        parents={id(button):document,id(document):root,id(root):None}
        walker.GetParentElement.side_effect=lambda item:parents[id(item)]
        return root,document,button,walker,parents

    def test_parent_context_matches_capture_and_detects_reused_control_on_new_page(self):
        root,document,button,walker,_=self.context_chain()
        expected=computer_observation.identity_key('window',tuple(
            computer_observation.context_descriptor(item) for item in (root,document,button)))
        actual=computer_observation.current_control_context(walker,button,(1,),'window')
        self.assertEqual(actual,expected)
        document.CurrentName='Payment confirmation'
        self.assertNotEqual(computer_observation.current_control_context(walker,button,(1,),'window'),expected)
        document.CurrentName='Home'
        document.GetRuntimeId=lambda:(9,)
        self.assertNotEqual(computer_observation.current_control_context(walker,button,(1,),'window'),expected)

    def test_context_requires_attested_root_and_rejects_cycles_or_missing_runtime(self):
        root,document,button,walker,parents=self.context_chain()
        parents[id(document)]=button
        with self.assertRaises(PermissionError):
            computer_observation.current_control_context(walker,button,(1,),'window')
        parents[id(document)]=None
        with self.assertRaises(PermissionError):
            computer_observation.current_control_context(walker,button,(1,),'window')
        button.GetRuntimeId=lambda:()
        with self.assertRaises(PermissionError):
            computer_observation.current_control_context(walker,button,(1,),'window')

    def test_password_or_blocked_parent_context_cannot_be_used(self):
        root,document,button,walker,_=self.context_chain()
        document.CurrentIsPassword=True
        with self.assertRaises(PermissionError):
            computer_observation.current_control_context(walker,button,(1,),'window')
        document.CurrentIsPassword=False
        document.CurrentName=r'C:\Users\vijay koripella'
        with self.assertRaises(PermissionError):
            computer_observation.current_control_context(walker,button,(1,),'window')

    def test_focus_normal_request_is_verified_and_windows_refusal_is_not_bypassed(self):
        root, automation, user32 = Mock(), Mock(), Mock()
        root.CurrentProcessId=456
        automation.ElementFromHandle.return_value=root
        user32.GetForegroundWindow.side_effect=[999,123]
        with patch.object(computer_observation,'select_window',return_value=(123,456,'Spotify',789)), patch.object(computer_observation,'automation_client',return_value=automation), patch.object(computer_observation.ctypes,'WinDLL',return_value=user32):
            self.assertTrue(computer_observation.focus('Spotify')['focused'])
        user32.SetForegroundWindow.assert_called_once_with(123)
        user32.GetForegroundWindow.side_effect=None
        user32.GetForegroundWindow.return_value=999
        user32.SetForegroundWindow.return_value=False
        with patch.object(computer_observation,'select_window',return_value=(123,456,'Spotify',789)), patch.object(computer_observation,'automation_client',return_value=automation), patch.object(computer_observation.ctypes,'WinDLL',return_value=user32):
            with self.assertRaises(computer_observation.ForegroundUnavailableError) as error: computer_observation.focus('Spotify')
            self.assertEqual(error.exception.diagnostic,'foreground_request_denied')

    def test_asynchronous_foreground_verification_is_bounded_and_never_retries_input(self):
        user32=Mock()
        user32.GetForegroundWindow.side_effect=[999,999,123]
        with patch.object(computer_observation.time,'sleep') as sleep:
            self.assertTrue(computer_observation.await_foreground(user32,123))
        self.assertEqual(sleep.call_count,2)
        user32.SetForegroundWindow.assert_not_called()
        user32.GetForegroundWindow.side_effect=None
        user32.GetForegroundWindow.return_value=999
        with patch.object(computer_observation.time,'monotonic',side_effect=[0,.1,.6]), patch.object(computer_observation.time,'sleep'):
            self.assertFalse(computer_observation.await_foreground(user32,123))

    def test_target_privilege_detection_fails_closed_and_releases_token(self):
        import ctypes
        from ctypes import wintypes as w
        kernel, advapi = Mock(), Mock()
        advapi.OpenProcessToken.return_value = False
        self.assertFalse(computer_observation.normal_process_token(kernel, advapi, 7))
        kernel.CloseHandle.assert_not_called()
        def opened(handle, rights, token):
            ctypes.cast(token, ctypes.POINTER(w.HANDLE))[0] = 42
            return True
        advapi.OpenProcessToken.side_effect = opened
        def information(token, kind, elevation, size, returned):
            ctypes.cast(elevation, ctypes.POINTER(w.DWORD))[0] = 0
            ctypes.cast(returned, ctypes.POINTER(w.DWORD))[0] = ctypes.sizeof(w.DWORD)
            return True
        advapi.GetTokenInformation.side_effect = information
        self.assertTrue(computer_observation.normal_process_token(kernel, advapi, 7))
        self.assertEqual(kernel.CloseHandle.call_args.args[0].value, 42)
        advapi.GetTokenInformation.side_effect = None
        advapi.GetTokenInformation.return_value = False
        self.assertFalse(computer_observation.normal_process_token(kernel, advapi, 7))

    def test_focus_accepts_exact_permission_but_inspection_stays_fresh(self):
        store, broker = Mock(), Mock()
        store.has_permission.return_value = True
        broker.focus_app.return_value = {'focused': True}
        self.assertEqual(permissions.dispatch(store, broker, 'focus_app', 'Spotify')['source'], 'persistent')
        store.has_permission.assert_called_once_with('focus_app', 'Spotify')
        broker.focus_app.assert_called_once_with('Spotify', approved=True)
        self.assertEqual(permissions.dispatch(store, broker, 'inspect_app', 'Spotify')['status'], 'approval_required')
        with self.assertRaises(PermissionError): permissions.dispatch(store, broker, 'inspect_app', 'Spotify', 'always_allow')
    def test_window_identity_changes_with_process_lifetime_and_provider_identity(self):
        key = computer_observation.identity_key(123, 456, 789, (1, 2, 3))
        self.assertEqual(key, computer_observation.identity_key(123, 456, 789, (1, 2, 3)))
        self.assertNotEqual(key, computer_observation.identity_key(123, 456, 790, (1, 2, 3)))
        self.assertNotEqual(key, computer_observation.identity_key(123, 456, 789, (1, 2, 4)))

    def test_glow_and_observation_share_app_identity(self):
        from tool_broker import ALLOWED_APPS
        from window_glow import accepts_glow_process
        self.assertTrue(accepts_glow_process('chrome.exe', ALLOWED_APPS['Chrome']))
        self.assertFalse(accepts_glow_process('chrome.exe', r'C:\Users\tejas\chrome.exe'))
        self.assertFalse(accepts_glow_process('spotify.exe', r'C:\Users\tejas\Spotify.exe', 'unrelated_package'))
        with self.assertRaises(PermissionError):
            accepts_glow_process('chrome.exe', r'C:\Users\vijay koripella\chrome.exe')

    def test_identity_is_configured_executable_or_exact_package(self):
        from tool_broker import ALLOWED_APPS
        self.assertTrue(capability_registry.accepts_process('Chrome', ALLOWED_APPS['Chrome']))
        self.assertFalse(capability_registry.accepts_process('Chrome', r'C:\Users\tejas\chrome.exe'))
        self.assertFalse(capability_registry.accepts_process('Spotify', r'C:\Users\tejas\Spotify.exe', 'unrelated_package'))
        self.assertTrue(capability_registry.accepts_process('Spotify', r'C:\Program Files\WindowsApps\Spotify\Spotify.exe', 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0'))

    def test_registry_does_not_advertise_unimplemented_input_or_playlists_playing(self):
        rows = capability_registry.application_capabilities()
        self.assertTrue(all(not row['generic_input_available'] for row in rows))
        spotify = next(row for row in rows if row['app'] == 'Spotify')
        inspection = next(item for item in spotify['capabilities'] if item['name'] == 'inspect_window')
        self.assertFalse(inspection['persistent_eligible'])
        playlist = next(item for item in spotify['capabilities'] if item['name']=='play_registered_playlist')
        self.assertEqual(playlist['tool'],'spotify_playback')
        self.assertEqual(playlist['verification'],'playlist_scoped_uia_control_and_spotify_media_session')
    def test_rejects_unknown_targets_and_blocked_content(self):
        for target in ('Windows', 'powershell', r'C:\Users\vijay koripella', 'Spotify Web'):
            with self.assertRaises(PermissionError): computer_observation.select_window(target)
        with self.assertRaises(PermissionError): computer_observation.safe_label(r'C:\Users\vijay koripella\notes')
        self.assertEqual(len(computer_observation.safe_label('x' * 1000)), 240)

    def test_inspection_never_uses_persistent_permission(self):
        store, broker = Mock(), Mock()
        store.has_permission.return_value = True
        result = permissions.dispatch(store, broker, 'inspect_app', 'Spotify')
        self.assertEqual(result['status'], 'approval_required')
        broker.inspect_app.assert_not_called()
        store.has_permission.assert_not_called()
        with self.assertRaises(PermissionError): permissions.dispatch(store, broker, 'inspect_app', 'Spotify', 'always_allow')
        observation = {'controls': [{'name': 'Play'}], 'partial': False, 'read_only': True}
        broker.inspect_app.return_value = {'observation': observation}
        with patch('permissions.action_glow'):
            result = permissions.dispatch(store, broker, 'inspect_app', 'Spotify', 'allow_once')
        broker.inspect_app.assert_called_once_with('Spotify', approved=True)
        self.assertEqual(result['observation'], observation)
        self.assertNotIn('Windows', result['message'])

    def test_stop_blocks_inspection_before_dispatch(self):
        store, broker = Mock(), Mock()
        safety.safety.stop('inspection test')
        with self.assertRaises(safety.StoppedError): permissions.dispatch(store, broker, 'inspect_app', 'Spotify', 'allow_once')
        broker.inspect_app.assert_not_called()
