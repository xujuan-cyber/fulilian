import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'

// Which translucency the OS can back. Asked synchronously because the renderer
// needs it before its first paint, and answered by main because deciding it
// needs `os.release()` — a sandboxed preload may only require electron, events,
// timers and url, so importing node:os here throws before contextBridge runs
// and takes the ENTIRE bridge down with it (window.fulilianDesktop undefined =>
// "Desktop IPC bridge is unavailable"). No reply means no glass, which degrades
// to an ordinary opaque window rather than a page thinned over nothing.
const translucencySupport = ipcRenderer.sendSync('fulilian:translucency:support')
const hudWindowing = ipcRenderer.sendSync('fulilian:hud:windowing')
const hudNativeDrag = hudWindowing?.nativeDrag === true

contextBridge.exposeInMainWorld('fulilianDesktop', {
  glassSupported: translucencySupport?.glass === true,
  translucencySupported: translucencySupport?.translucency === true,
  getConnection: profile => ipcRenderer.invoke('fulilian:connection', profile),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('fulilian:connection:for', payload),
  getProfileRoutes: profiles => ipcRenderer.invoke('fulilian:plugin-profile-routes', profiles),
  revalidateConnection: () => ipcRenderer.invoke('fulilian:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('fulilian:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('fulilian:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('fulilian:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('fulilian:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('fulilian:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('fulilian:window:openInTerminal', sessionId, opts),
  openWindow: () => ipcRenderer.invoke('fulilian:window:openInstance'),
  openBrowserWindow: tabId => ipcRenderer.invoke('fulilian:window:openBrowser', tabId),
  onBrowserPopoutClosed: callback => {
    const listener = (_event, tabId) => callback(tabId)
    ipcRenderer.on('fulilian:browser-popout:closed', listener)

    return () => ipcRenderer.removeListener('fulilian:browser-popout:closed', listener)
  },
  claimAmbientCue: key => ipcRenderer.invoke('fulilian:ambient:claim', key),
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('fulilian:wake-indicator:get'),
    setState: state => ipcRenderer.send('fulilian:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('fulilian:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('fulilian:wake-indicator:state', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('fulilian:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('fulilian:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('fulilian:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('fulilian:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('fulilian:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('fulilian:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('fulilian:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('fulilian:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('fulilian:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    nativeDrag: hudNativeDrag,
    windowing: {
      clientPlacement: hudWindowing?.clientPlacement !== false,
      controlDrag: hudWindowing?.controlDrag === true,
      nativeDrag: hudNativeDrag,
      workspaceTransfer: hudWindowing?.workspaceTransfer === true
    },
    open: request => ipcRenderer.invoke('fulilian:hud:open', request),
    close: () => ipcRenderer.invoke('fulilian:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('fulilian:hud:ignore-mouse', ignore),
    moveBy: delta => ipcRenderer.send('fulilian:hud:move-by', delta),
    setWorkspaceTransfer: transferring => ipcRenderer.send('fulilian:hud:workspace-transfer', transferring),
    setBounds: bounds => ipcRenderer.send('fulilian:hud:set-bounds', bounds),
    resetLayout: () => ipcRenderer.invoke('fulilian:hud:reset-layout'),
    // Whether the band covers the window below the bar. Main pairs it with the
    // user's translucency setting to decide the native frost (macOS vibrancy /
    // Windows 11 DWM backdrop) — see hudFrostFor.
    setFrost: showing => ipcRenderer.invoke('fulilian:hud:frost', showing),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('fulilian:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('fulilian:hud:goto', listener)

      return () => ipcRenderer.removeListener('fulilian:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('fulilian:hud:changed', listener)

      return () => ipcRenderer.removeListener('fulilian:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('fulilian:hud:cursor', listener)

      return () => ipcRenderer.removeListener('fulilian:hud:cursor', listener)
    },
    // Main's game-overlay watch: whether a fullscreen app (a game) is under
    // the HUD, so the renderer can step back to the low-opacity overlay
    // treatment while one owns the screen.
    onGameOverlay: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('fulilian:hud:game-overlay', listener)

      return () => ipcRenderer.removeListener('fulilian:hud:game-overlay', listener)
    }
  },
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('fulilian:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('fulilian:quick-entry:settings:set', patch),
    submit: payload => ipcRenderer.send('fulilian:quick-entry:submit', payload),
    dismiss: () => ipcRenderer.send('fulilian:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('fulilian:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('fulilian:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('fulilian:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('fulilian:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('fulilian:quick-entry:shown', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('fulilian:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('fulilian:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('fulilian:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('fulilian:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('fulilian:connection-config:test', payload),
  // Opt-in OS-keychain encryption for stored gateway secrets (default off —
  // see secret-storage-policy.ts). get never touches the OS keychain.
  getSecretStorageEncryption: () => ipcRenderer.invoke('fulilian:secret-storage:get'),
  setSecretStorageEncryption: (on: boolean) => ipcRenderer.invoke('fulilian:secret-storage:set', on),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('fulilian:connections:list'),
    save: payload => ipcRenderer.invoke('fulilian:connections:save', payload),
    remove: id => ipcRenderer.invoke('fulilian:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('fulilian:connections:set-primary', id),
    setLaunchMode: mode => ipcRenderer.invoke('fulilian:connections:set-launch-mode', mode),
    setLastUsed: id => ipcRenderer.invoke('fulilian:connections:set-last-used', id),
    test: id => ipcRenderer.invoke('fulilian:connections:test', id),
    updateManaged: id => ipcRenderer.invoke('fulilian:connections:update-managed', id),
    // Fan out `fulilian update` to every eligible registered connection.
    // Optional excludeIds skips rows the caller updates through another path.
    updateAll: options => ipcRenderer.invoke('fulilian:connections:update-all', options),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:connections:changed', listener)

      return () => ipcRenderer.removeListener('fulilian:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('fulilian:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('fulilian:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('fulilian:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('fulilian:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('fulilian:connection-config:oauth-logout', remoteUrl),
  // Fulilian Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('fulilian:cloud:status'),
    login: () => ipcRenderer.invoke('fulilian:cloud:login'),
    logout: () => ipcRenderer.invoke('fulilian:cloud:logout'),
    discover: org => ipcRenderer.invoke('fulilian:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('fulilian:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    get: () => ipcRenderer.invoke('fulilian:profile:get'),
    remember: name => ipcRenderer.invoke('fulilian:profile:remember', name),
    set: name => ipcRenderer.invoke('fulilian:profile:set', name)
  },
  api: request => ipcRenderer.invoke('fulilian:api', request),
  notify: payload => ipcRenderer.invoke('fulilian:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('fulilian:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('fulilian:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('fulilian:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('fulilian:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('fulilian:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('fulilian:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('fulilian:readFileText', filePath),
  readPluginSource: (filePath: string) => ipcRenderer.invoke('fulilian:readPluginSource', filePath),
  selectPaths: options => ipcRenderer.invoke('fulilian:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('fulilian:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('fulilian:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('fulilian:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('fulilian:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('fulilian:saveImageFromUrl', url),
  contextMenuEdit: command => ipcRenderer.invoke('fulilian:context-menu:edit', command),
  contextMenuCopyImage: () => ipcRenderer.invoke('fulilian:context-menu:copy-image'),
  contextMenuSpellcheck: action => ipcRenderer.invoke('fulilian:context-menu:spellcheck', action),
  contextMenuGuestAddWord: payload => ipcRenderer.invoke('fulilian:context-menu:guest-add-word', payload),
  onContextMenuSpellcheck: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:context-menu-spellcheck', listener)

    return () => ipcRenderer.removeListener('fulilian:context-menu-spellcheck', listener)
  },
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('fulilian:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('fulilian:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('fulilian:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('fulilian:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('fulilian:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('fulilian:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('fulilian:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('fulilian:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('fulilian:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('fulilian:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('fulilian:keep-awake', on),
  setDisableF12: blocked => ipcRenderer.send('fulilian:devtools:disable-f12', blocked),
  setPreviewShortcutActive: active => ipcRenderer.send('fulilian:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('fulilian:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('fulilian:openPreviewInBrowser', url),
  reachPreviewUrl: url => ipcRenderer.invoke('fulilian:preview:reach', url),
  setActiveConnectionRoute: route => ipcRenderer.send('fulilian:connection:active-route', route),
  fetchLinkTitle: url => ipcRenderer.invoke('fulilian:fetchLinkTitle', url),
  resolveFavicon: url => ipcRenderer.invoke('fulilian:resolveFavicon', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('fulilian:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('fulilian:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('fulilian:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('fulilian:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('fulilian:zoom:get'),
    // Synchronous zoom factor (1 = 100%). Coordinate math needs it in the
    // same tick as the event it converts, so no IPC round-trip here.
    factor: () => webFrame.getZoomFactor(),
    setPercent: percent => ipcRenderer.send('fulilian:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:zoom:changed', listener)

      return () => ipcRenderer.removeListener('fulilian:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('fulilian:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('fulilian:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('fulilian:logs:renderer-error', report),
  readDir: dirPath => ipcRenderer.invoke('fulilian:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('fulilian:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('fulilian:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('fulilian:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('fulilian:fs:desktopPluginsRoot'),
  logsRoot: () => ipcRenderer.invoke('fulilian:fs:logsRoot'),
  agentPluginsRoot: () => ipcRenderer.invoke('fulilian:fs:agentPluginsRoot'),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('fulilian:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('fulilian:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('fulilian:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('fulilian:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('fulilian:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('fulilian:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('fulilian:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('fulilian:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('fulilian:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('fulilian:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('fulilian:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('fulilian:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('fulilian:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('fulilian:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('fulilian:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('fulilian:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('fulilian:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('fulilian:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('fulilian:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('fulilian:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('fulilian:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('fulilian:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('fulilian:git:review:prList', repoPath, branches, numbers),
      fetchPrComment: (repoPath, url) => ipcRenderer.invoke('fulilian:git:review:fetchPrComment', repoPath, url),
      createPr: repoPath => ipcRenderer.invoke('fulilian:git:review:createPr', repoPath)
    }
  },
  terminal: {
    cwd: id => ipcRenderer.invoke('fulilian:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('fulilian:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('fulilian:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('fulilian:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('fulilian:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `fulilian:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `fulilian:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('fulilian:close-preview-requested', listener)
  },
  onPreviewNav: callback => {
    const listener = (_event, command) => callback(command)
    ipcRenderer.on('fulilian:preview-nav', listener)

    return () => ipcRenderer.removeListener('fulilian:preview-nav', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('fulilian:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:open-updates', listener)

    return () => ipcRenderer.removeListener('fulilian:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:deep-link', listener)

    return () => ipcRenderer.removeListener('fulilian:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('fulilian:deep-link-ready'),
  probePluginRepo: payload => ipcRenderer.invoke('fulilian:plugin:probe', payload),
  installDesktopPlugin: payload => ipcRenderer.invoke('fulilian:plugin:installDesktop', payload),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:window-state-changed', listener)

    return () => ipcRenderer.removeListener('fulilian:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('fulilian:focus-session', listener)

    return () => ipcRenderer.removeListener('fulilian:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:notification-action', listener)

    return () => ipcRenderer.removeListener('fulilian:notification-action', listener)
  },
  onNotificationActivate: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:notification-activate', listener)

    return () => ipcRenderer.removeListener('fulilian:notification-activate', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('fulilian:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:backend-exit', listener)

    return () => ipcRenderer.removeListener('fulilian:backend-exit', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:connection:applied', listener)

    return () => ipcRenderer.removeListener('fulilian:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:power-resume', listener)

    return () => ipcRenderer.removeListener('fulilian:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('fulilian:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('fulilian:power-battery', listener)

    return () => ipcRenderer.removeListener('fulilian:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:boot-progress', listener)

    return () => ipcRenderer.removeListener('fulilian:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('fulilian:bootstrap:get'),
  continueBootstrapLocal: () => ipcRenderer.invoke('fulilian:bootstrap:continue-local'),
  resetBootstrap: () => ipcRenderer.invoke('fulilian:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('fulilian:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('fulilian:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fulilian:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('fulilian:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('fulilian:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('fulilian:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('fulilian:uninstall:summary'),
    run: mode => ipcRenderer.invoke('fulilian:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('fulilian:updates:check'),
    apply: opts => ipcRenderer.invoke('fulilian:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('fulilian:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('fulilian:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fulilian:updates:progress', listener)

      return () => ipcRenderer.removeListener('fulilian:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('fulilian:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('fulilian:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('fulilian:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('fulilian:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('fulilian:found-in-page', listener)

    return () => ipcRenderer.removeListener('fulilian:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fulilian:open-find-bar', listener)

    return () => ipcRenderer.removeListener('fulilian:open-find-bar', listener)
  }
})
