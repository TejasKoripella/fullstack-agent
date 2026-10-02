# Jarvis local assistant

Jarvis is a local Qwen assistant with browser chat, long-term memory, push-to-talk and optional local wake listening, one-shot vision, and named Windows tools. Qwen can request existing named tools through the security and permission broker; it has no shell access.

## Run

From this project folder, without Administrator privileges:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The server refuses to start elevated. If port 8000 is already occupied, stop the older Jarvis server before starting this command.

Ollama must be running with `qwen3.5:4b` installed. Chat currently requests CPU inference because CUDA initialization crashed on this PC. `GET /health` reports whether Ollama can see the model.

## Using the interface

- Home uses a black and white desktop layout with the blue particle core and a slowly moving starfield. Once a chat has messages, the core shrinks into a status strip and the conversation fills the workspace. Reduced motion stops the decorative animation. The sidebar has one permanent **Master Chat** and lists saved Side Chats. Tools & settings contains status, wake settings, vision, memory, app workflows, permissions, and developer diagnostics. The visuals use local HTML/CSS/JavaScript and no paid assets.
- Type a message and press Enter or **Send**; Shift+Enter inserts a new line. Qwen responses stream as they are generated. **Master Chat** retains history across browser, server, and computer restarts. It cannot be renamed or deleted through the normal API or UI. **New Side Chat** opens an unsaved draft: no conversation row exists until its first response finishes successfully. Leaving or refreshing an untouched draft saves nothing. A model failure on the first send also creates no row.
- Master and Side Chats use the same full-width conversation workspace, composer, streaming, orb, and voice controls. Clicking either in the sidebar switches that workspace. Side Chats read relevant long-term memory, a compact recent Master context, and their own recent history. Python prevents Side Chats from automatically saving facts or exchanges to long-term memory, including with `save=true`. A compact header menu offers **Move to Master**, **Commit to Memory**, and **Discard**. Move merges messages into the canonical Master while preserving the source archive. Commit explicitly copies completed exchanges into recall and saves eligible user-stated facts without moving the Side Chat; repeated commits do not duplicate the same exchanges. Discard requires confirmation before removing saved side history.
- Replies wait with pulsing dots and reveal incoming text fragments softly. State labels crossfade, Thinking has a restrained letter ripple, and orb speed/energy ease between states without resetting their phase. Reduced motion disables decorative motion and text animations. Developer mode has visual previews for all states; previews do not start microphones, speech, or tools.
- Master messages participate in retrieval automatically, and directly stated stable facts are saved under the user's standing approval. The **Save the next full chat exchange** option remains compatible with the older exchange memory store. Secret-like facts and questions are excluded by a conservative extractor. Prompt construction uses at most 12 recent messages under a character budget, six retrieved items, bounded structured state, and four short Master snippets for a side branch. The entire lifetime transcript is never sent to Qwen.
- Choose a microphone in Tools & settings, then hold the mic button to record and release it to transcribe. The selected device is used for both push-to-talk and wake listening. The browser stops the microphone track and local Whisper puts the transcript in the text box for review. Recording stops after 20 seconds, or if the tab loses focus. The server rejects audio longer than 30 seconds. Audio is not saved to disk.
- Enable **Listen for “Hey Jarvis”** in Tools & settings and choose the default, laptop, or another available microphone. Short voice-active windows are checked by local Whisper. Basic sound-level filtering skips silent windows, and only one wake check runs at a time in the page so listening does not pile up CPU work while Qwen is responding. A detected wake phrase either puts trailing command text in the message bar or records up to eight more seconds for review. Switching wake listening OFF releases the microphone; it also stops when the page closes. Browser background throttling may limit wake reliability. This is not yet an always-on Windows service. On this PC, Windows currently has no usable default input, so both tested browsers report `NotFoundError` until an input is connected or enabled in Windows Sound settings.
- **Speak replies** uses an installed local browser voice when available, then the local Piper Ryan voice through `/voice/speak`. The supplied Windows desktop voices enumerate but fail to synthesize on this machine, so Piper is the working offline path. Text appears before speech is generated. The Piper model is stored in `voices/` and does not require a paid account or cloud service. If the virtual environment is recreated, install `piper-tts` and download `en_US-ryan-medium` into `voices/` with `python -m piper.download_voices --download-dir voices en_US-ryan-medium`.
- **Camera frame** and **Screen frame** capture one image and stop the video track immediately. The image is sent only with the next message. Saved exchanges contain text, not image bytes.
- The Memory Vault supports named facts with confirmation for manual edits. Existing preferences and project state also participate in retrieval. Recalled data is given to the model as untrusted context.
- The file inspector reads project text files without a prompt. It excludes `data`, `config`, `.venv`, `.git`, and `__pycache__` and cannot write or delete files.
- A typed or transcribed request mentioning Chrome, Epic, Windows Documents, or Spotify starts its named workflow. Opening an app, site, settings page, or this user's Windows Documents folder requires a first-time choice: Allow Once, Always Allow, or Deny. Always Allow saves that exact action and target in SQLite; later matching requests run immediately, and the permission can be revoked in Tools & settings. The Windows Documents open action requests Explorer for this user's verified Documents folder. Jarvis can also list that folder inside Tools & settings; selecting a file reads only that TXT, MD, CSV, JSON, or DOCX file under size limits.

Action metadata, without audio or image content, is kept in `data/jarvis.db` for audit. Conversation text is also kept there as local history. Existing main conversation messages migrate into one canonical Master without deletion or duplicate memory creation. Their original source IDs remain in `origin_conversation_id`; original conversation rows and titles are retained as archives. Empty legacy side drafts are archived without removing rows. Initialization is idempotent, and a partial unique index enforces one canonical Master. The pre-migration SQLite snapshot is under `data/backups/`.

## App control

`config/allowed_apps.json` contains the Epic Games Launcher executable found on this PC, following the user's explicit request. Add other app names and exact absolute `.exe` paths only after the user approves them, then restart Jarvis. For example, after choosing a specific installed app:

```json
{ "My Editor": "C:\\exact\\approved\\path\\Editor.exe" }
```

The HTTP API cannot change this allowlist. Named open actions pass hard security validation before the saved permission lookup and write audit records with their authorization source. Closing still asks for confirmation. Jarvis launches allowlisted executables without a shell or arguments. It can send a graceful close request only to an app it launched during the current server session; the app may ask you about unsaved work. It never force-kills a process.

Other app workflows can be added as named, opt-in adapters with the same approval and audit rules. No external app, OpenClaw plugin, or unrestricted command runner is connected by default.

The current named workflow can open Epic, request the registered Spotify Windows app, list and read selected files in the user's Windows Documents, launch Chrome without URLs or extra arguments, request Spotify Web in the PC browser, and open Bluetooth or Sound settings. A browser or Windows launch request does not prove that the destination loaded. To check Epic update status, use **Screen frame** after opening it and send the image to Jarvis. Jarvis can read the Windows media-session status for Spotify and request Play or Pause only for Spotify, with the same first-use permission and audit process. A media session appears after a track is started in Spotify; no session is available on this PC at the moment. Windows sound output determines whether playback goes to the Bluetooth speaker. Bluetooth pairing and output selection still need the adapter and speaker, then a manual handoff through Windows settings. Direct control of any arbitrary application is not available: an unrestricted click/type agent could delete data through an app's own interface, which would violate the no-deletion requirement.

Spotify media control uses free local Python/WinRT packages. If the virtual environment is recreated, install them with:

```powershell
.\.venv\Scripts\python.exe -m pip install winrt-Windows.Media.Control==3.2.1 winrt-Windows.Foundation==3.2.1 winrt-Windows.Foundation.Collections==3.2.1
```

## Private phone access

The web interface has a PWA manifest, mobile layout, and home-screen icons. Jarvis stays bound to `127.0.0.1`. If Tailscale is already installed and your PC and phone are in the same tailnet, Tailscale Serve can provide a private HTTPS address:

```powershell
tailscale serve --bg 127.0.0.1:8000
tailscale serve status
```

Review the tailnet's access policy before using the address on the phone. Use Tailscale **Serve**, not public **Funnel**. Do not bind Uvicorn to `0.0.0.0`. Tailscale setup may require separate user-managed installation and sign-in; Jarvis does not request Administrator privileges.

Reference: [Tailscale Serve documentation](https://tailscale.com/docs/reference/tailscale-cli/serve).

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_app test_master_chat test_model_tools test_privileges
.\.venv\Scripts\python.exe test_security.py
node test_voice_lifecycle.cjs
node test_capture_lifecycle.cjs
```

`test_memory.py` now uses a temporary database. Full discovery is safe to run with `.\.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -q`.

For an optional live Qwen check of Master fact saving and Side memory reading, run `.\.venv\Scripts\python.exe verify_master_model.py`. It uses a separate temporary database and leaves production facts unchanged.

Chrome launch is delegated to Windows with the configured executable only. It creates no Jarvis-owned browser handle and cannot be closed through Jarvis. Google Docs has been removed from the site allowlist and UI. Browser actions require a normal, non-administrator Windows token; restricted or uncertain launch contexts fail closed. A live normal-user launch was confirmed working. See LOCAL_VERIFICATION.md for remaining browser cases and limits of the root-cause evidence.

## Emergency Stop

Use Emergency Stop in Tools & settings, or Ctrl+Alt+J while the Jarvis page is focused. It cancels generation, speech helpers, listening, capture, and approvals and blocks new actions. The stopped state persists across restart. Resume Jarvis is a deliberate user control; it does not restart cancelled actions or listening. Shared browser/application processes are never terminated by the browser launch path. Only retained Jarvis-owned helper/app handles can be stopped.

## Named resources

`config/known_resources.json` is a local, manually maintained alias list. The initial aliases are **Jarvis project** (this folder in VS Code) and **Jarvis verification** (LOCAL_VERIFICATION.md in its Windows-associated viewer). Ask “Open Jarvis project” or “Open Jarvis verification.” The model requests `open_resource`; each request requires fresh Allow Once approval. Saved grants cannot authorize these actions.

Only configured aliases are accepted. Documents must already exist and use .txt, .md, .pdf, or .docx; projects must be existing directories. Resolved paths must remain inside the current Windows profile and outside the permanently blocked profile. Neither model calls nor HTTP requests can modify this registry. Windows receives a file request or a supported VS Code file URI; no shared application handle is owned or terminated. Opening does not run a terminal command or imply the document loaded successfully.

Registered webpages use `{"kind":"webpage","url":"https://docs.python.org/3/"}`. The built-in alias “Python documentation” works from chat or Saved resources. Each opening requires fresh Allow Once approval and uses Windows' default browser. The registry accepts fixed HTTPS links with DNS hostnames and plain paths, without credentials, query strings, fragments, nonstandard ports or local host/IP literals. Qwen supplies only a registered alias, never a URL. Jarvis does not fetch page text, manage browser processes, or claim the destination loaded merely because Windows accepted the request.

VS Code URI reference: [official VS Code documentation](https://code.visualstudio.com/docs/configure/command-line).

Registered Spotify playlists use `{"kind":"playlist","uri":"spotify:playlist:<22-character Spotify ID>"}` in the same local alias registry. Request the alias with “Open …” and approve Allow Once. Only playlist URIs are accepted, without URL parameters, autoplay suffixes, or arbitrary schemes. The Windows Spotify protocol handler receives the URI; Jarvis does not launch a browser or own Spotify. Opening a playlist does not confirm playback. No personal playlist is configured yet.

URI reference: [Spotify URI documentation](https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids).

Tools & settings includes filename search in Windows Documents. It reads names only, excludes child links/reparse points and hidden folders, and reports incomplete searches when it hits traversal/result limits or unavailable folders. Select a result to explicitly read that document through the existing guarded reader. Chat also supports direct requests such as “Find filenames containing robotics in Windows Documents.” Only a filename fragment present in the current request can be searched; search never automatically reads or opens a result.

Optional real-model check: `.\.venv\Scripts\python.exe verify_document_search.py` uses disposable files and temporary Side Chat storage.

Optional compound-request check: `.\.venv\Scripts\python.exe verify_compound_tools.py` asks real Qwen for both built-in resource aliases using temporary Side storage. It verifies independent approvals and blocks all Windows launches during the check.

Optional older-history recall check: `.\.venv\Scripts\python.exe verify_old_history.py` uses a disposable Master history with 100 newer weak topic matches and verifies real Qwen Side recall without saving durable facts.

After explicitly reading a document in Settings, select “Use document in next message” to attach its text to one chat request. The composer offers removal; sending or switching chats clears the attachment. References are limited to 6000 characters and treated as untrusted data. The reference itself is not automatically saved as long-term memory. Optional real-model check: `.\.venv\Scripts\python.exe verify_document_context.py` uses disposable files and Side storage.

The project-file inspector also offers “Use project file in next message” after an explicit successful read. This reuses the existing Jarvis-only text reader, including excluded folders, blocked paths and file-size checks. Only one document/project reference is attached per message; sending, switching chats or Emergency Stop clears it. Late inspection results cannot appear in another chat or after Stop. This does not grant Qwen a general filesystem tool or access to other projects.

When a message explicitly combines a tool action with “and explain/help/summarize/describe,” Jarvis preserves the action receipts and streams a separate tool-free explanation. Approval controls appear before the explanation finishes. This follow-up cannot launch additional tools; failed explanations leave the action receipts available. Plain action requests use the original single-call path.

Chat actions now go through Qwen's structured intent proposal, known-target validation, and the existing permission/security/tool broker. Minor registered-target typos can resolve safely; ambiguous or low-confidence proposals ask for clarification. Recent target references are limited to one chat, five minutes and the current safety epoch. The configured Default playlist opens in Spotify; it does not claim playback.

Future feature acceptance requires testing the actual browser UI and recording visible results in LOCAL_VERIFICATION.md. Unit/API success alone does not establish user-facing functionality. Physical device checks and remote access stay deferred until the user explicitly resumes them.

## Approved window observation

Optional Windows accessibility dependency: install `requirements-computer-use.txt` in the existing virtual environment. Tools & settings offers Inspect selected window for configured Chrome and packaged Spotify. Every snapshot requires fresh Allow Once; persistent opening permission does not grant inspection. The existing security/permission/broker/audit pipeline remains authoritative.

`computer_controller.py` validates bounded worker snapshots as untrusted data, strips unexpected fields, checks the app/mode/control schema, and rejects stale safety epochs. The private worker reads control names only, skips password controls, and reports traversal limits. A snapshot can contain offscreen control labels and is not proof that a page or playlist finished loading. Chat can propose the existing inspector for an explicit request such as “look at Spotify”; the backend still requires fresh approval. No generic clicking, typing or arbitrary process control is available yet.

Chrome and Spotify border selection shares the configured executable/package identity policy with observation. Visual movement/resize/cursor lifecycle verification remains unfinished. The main architecture is not frozen; use the eight architecture gates recorded in LOCAL_VERIFICATION.md before requesting a lower thinking level.

### Control identity contract (architecture still unfinished)

Approved snapshots now include a window comparison identifier derived from the window handle, process ID, process creation time and UIA runtime identifier. The observer re-attests the application and process lifetime at the end of traversal. Controls include opaque comparison identifiers and geometry; raw native handles are not returned by the controller.

`resolve_control` compares a previously intended control with a freshly approved snapshot, requires the same application/window/name/type, uses fresh bounds and rejects missing, ambiguous, disabled or offscreen targets. Controller-stamped safety epochs invalidate old references across Stop/Resume. Reference age is bounded to 60 seconds, fresh snapshots to five seconds. Expiry requests a new observation rather than falsely declaring Jarvis stopped. These are backend comparison contracts, not an input authorization, exposed click tool or finished computer-use controller.

UIA runtime identifiers may be reused and must be treated as opaque comparison values, not permanent identities or permissions: [Microsoft GetRuntimeId reference](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationelement-getruntimeid). A future input step still requires fresh target validation, action policy/approval, exact visible reticle readiness, cancellation, and post-action verification.

### Target preview (visual verification unfinished)

Approved UI inspection offers a compact control chooser and Show target. Preview once confirms bringing that app forward and highlighting the selected control for three seconds; it never clicks or types. Its reference is workspace-scoped, single-use, expires after 60 seconds and cannot survive Stop/Resume. The existing broker audits execution; only an owned helper draws the indicator and cancellation stops that helper. No model tool accepts raw coordinates or controls the overlay.

Live testing found unreliable Windows foreground handoff from the in-app browser. Normal Windows focus requests remain subject to OS restrictions; no bypass is implemented. One already-foreground attempt reported indicator readiness, but native visual alignment and the full overlay lifecycle are still unverified. See LOCAL_VERIFICATION.md for evidence and current limitations. Do not treat the preview as a finished input action or architecture freeze.

### Discuss an approved window snapshot

After an approved inspection, Use snapshot in next message attaches its bounded control labels to one normal chat request. The composer shows the selected app and offers Remove reference. Sending, switching workspaces or Emergency Stop clears the attachment. A snapshot is historical, may be incomplete, and does not prove current playback, page load or unobserved controls.

The backend keeps an expiring, single-use context reference separate from the preview reference. The context reference cannot authorize a preview or action; preview references cannot enter the conversation context. Workspace and safety-epoch checks prevent stale or cross-chat reuse. Qwen receives at most 6000 characters explicitly marked as untrusted UI data. Only the user's current message can request tools or supply automatically remembered facts. This reuses the existing conversation and memory pipeline; no second memory system or background observation is added.
