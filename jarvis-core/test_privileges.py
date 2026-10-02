import unittest
from unittest.mock import Mock, patch
import security


class PrivilegeTests(unittest.TestCase):
    def test_standard_user_is_allowed(self):
        with patch.object(security.os, "name", "nt"), patch.object(security.ctypes, "windll", Mock(), create=True) as windows:
            windows.shell32.IsUserAnAdmin.return_value = 0
            security.assert_not_admin()

    def test_elevated_user_is_rejected(self):
        with patch.object(security.os, "name", "nt"), patch.object(security.ctypes, "windll", Mock(), create=True) as windows:
            windows.shell32.IsUserAnAdmin.return_value = 1
            with self.assertRaises(PermissionError):
                security.assert_not_admin()

    def test_unavailable_privilege_check_fails_closed(self):
        for error in (AttributeError("unavailable"), OSError("unavailable")):
            with patch.object(security.os, "name", "nt"), patch.object(security.ctypes, "windll", Mock(), create=True) as windows:
                windows.shell32.IsUserAnAdmin.side_effect = error
                with self.assertRaises(PermissionError):
                    security.assert_not_admin()
