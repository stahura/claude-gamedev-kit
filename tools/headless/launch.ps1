# launch.ps1: start an unattended headless Claude Code run in this repo (Windows PowerShell). See docs/headless.md.
#
#   powershell -NoProfile -File tools/headless/launch.ps1 -Branch <run-branch> [-Prompt "<handoff line>"]
#              [-SessionId <uuid>] [-Python python] [-SkipSelftest] [-DryRun]
#
# Same steps as launch.sh: pre-launch checks, refuses while session.json's session is alive, session id (-SessionId,
# validated as a UUID, else a new one), resume command, then
#   claude -p "<handoff line>" --permission-mode acceptEdits --session-id <id> --output-format stream-json --verbose
# with KIT_HEADLESS=1 (Start-Process, so the claude pid is recorded in .claude/run-state/session.json with the session
# id, start time and branch; for a claude.cmd shim the recorded pid is the cmd.exe wrapper's); stream to
# build/headless/<id>.stream.jsonl; permission_denials -> .claude/run-state/denied.jsonl.
param(
    [string]$Branch = "",
    [string]$Prompt = "",
    [string]$SessionId = "",
    [string]$Python = "python",
    [switch]$SkipSelftest,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
function Die($msg) { [Console]::Error.WriteLine("launch: $msg"); exit 2 }
function Warn($msg) { [Console]::Error.WriteLine("launch: WARNING: $msg") }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) { Die "$Python not found" }
$Parsed = [guid]::Empty
if ($SessionId -and -not [guid]::TryParseExact($SessionId, "D", [ref]$Parsed)) {
    Die "-SessionId must be a UUID (e.g. $([guid]::NewGuid().ToString()))" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git not found" }
if (-not $DryRun -and -not (Get-Command claude -ErrorAction SilentlyContinue)) { Die "claude CLI not found" }

$Cur = (git rev-parse --abbrev-ref HEAD).Trim()
if (-not $Branch) { $Branch = $Cur }
if ($Cur -ne $Branch) { Die "run branch $Branch is not checked out (on $Cur): git fetch origin $Branch; git checkout $Branch" }
git ls-files --error-unmatch .claude/settings.json *> $null
if ($LASTEXITCODE -ne 0) { Die ".claude/settings.json is not committed" }
git diff --quiet HEAD -- .claude/settings.json
if ($LASTEXITCODE -ne 0) { Die ".claude/settings.json has uncommitted changes: commit the allowlist before launch" }
if (git status --porcelain --untracked-files=no) { Warn "uncommitted changes in tracked files" }
if (-not $env:CLAUDE_CODE_OAUTH_TOKEN -and -not $env:ANTHROPIC_API_KEY) {
    Warn "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set (fine only if this user is logged in)" }
$Trust = & $Python -c "import json,os,sys`np=os.path.join(os.path.expanduser('~'),'.claude.json')`ntry: d=json.load(open(p,encoding='utf-8'))`nexcept Exception: print('unknown'); sys.exit()`nprint(str(bool((d.get('projects') or {}).get(sys.argv[1],{}).get('hasTrustDialogAccepted'))).lower())" ($Root -replace '\\', '/')
if ($Trust -ne "true") { Warn "folder trust not recorded for $Root (run claude here once interactively and accept)" }
if (-not $SkipSelftest) {
    $st = & $Python tests/selftest.py | Select-Object -Last 1
    if ($st -notmatch "SELFTEST OK") { Die "selftest failed: run $Python tests/selftest.py" }
}

$Origin = ((git remote get-url origin) -replace '\.git$', '') -replace '^.*[:/]([^/:]+/[^/]+)$', '$1'
if (-not $Prompt) {
    $Prompt = "Read BRIEF.md in $Origin on branch $Branch; run it unattended per the run-protocol skill; report via run-report.json." }
$Sid = if ($SessionId) { $Parsed.ToString() } else { [guid]::NewGuid().ToString() }
$Slug = $Root -replace '[^A-Za-z0-9]', '-'
$ConfigDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$LogP = Join-Path (Join-Path (Join-Path $ConfigDir "projects") $Slug) "$Sid.jsonl"
$Head = (git rev-parse HEAD).Trim()
New-Item -ItemType Directory -Force -Path ".claude/run-state", "build/headless" | Out-Null
$Sess = "tools/headless/session.py"
if (Test-Path ".claude/run-state/session.json") {
    & $Python $Sess alive
    if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 3) {
        Die "session $(& $Python $Sess get session_id) (pid $(& $Python $Sess get pid)) is still running: stop it first (or resume it with tools/headless/resume.sh from Git Bash)" }
}
$Out = "build/headless/$Sid.stream.jsonl"
$Resume = "tools/headless/resume.sh --prompt `"<what changed, continue>`"   (kills a live session first; never two at once)"
[Console]::Error.WriteLine("launch: session $Sid on $Branch ($Head)")
[Console]::Error.WriteLine("launch: session log $LogP; stream $Out")
[Console]::Error.WriteLine("launch: resume with: $Resume")
$ClaudeArgs = @("-p", $Prompt, "--permission-mode", "acceptEdits", "--session-id", $Sid, "--output-format", "stream-json", "--verbose")
if ($DryRun) { [Console]::Error.WriteLine("launch: dry run, would run: claude " + ($ClaudeArgs -join " ")); exit 0 }
Remove-Item -Force -ErrorAction SilentlyContinue ".claude/run-state/session.json"
& $Python $Sess set "session_id=$Sid" "started=$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))" `
    "branch=$Branch" "head=$Head" "mode=headless" "log_path=$($LogP -replace '\\', '/')" "stream=$Out" "launcher=launch.ps1" "resumes=0"
if ($LASTEXITCODE -ne 0) { Die "cannot write session.json" }
$env:KIT_HEADLESS = "1"
# Start-Process (not &) so the claude pid is known; Windows command-line quoting for each argument.
function Quote-Arg([string]$a) {
    if ($a -notmatch '[\s"]') { return $a }
    return '"' + (($a -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' }
$Exe = (Get-Command claude -CommandType Application | Select-Object -First 1).Source
$ArgLine = ($ClaudeArgs | ForEach-Object { Quote-Arg $_ }) -join " "
if ($Exe -match '\.(cmd|bat)$') { $ArgLine = "/d /c `"`"$Exe`" $ArgLine`""; $Exe = "$env:ComSpec" }
$Proc = Start-Process -FilePath $Exe -ArgumentList $ArgLine -NoNewWindow -PassThru -RedirectStandardOutput $Out
& $Python $Sess set "pid=$($Proc.Id)"
[Console]::Error.WriteLine("launch: claude pid $($Proc.Id) (recorded in .claude/run-state/session.json)")
$Proc.WaitForExit()
$Rc = $Proc.ExitCode
& $Python $Sess denials $Out $Sid
[Console]::Error.WriteLine("launch: claude exited $Rc; resume with: $Resume")
exit $Rc
