<#
.SYNOPSIS
    Task runner for the Postgres Performance Lab.

.DESCRIPTION
    Stands in for the Makefile the spec asks for -- `make` is not installed on
    this machine. Same verbs.

        .\lab.ps1 up          start Postgres (builds the image on first run)
        .\lab.ps1 down        stop Postgres, keep the data volume
        .\lab.ps1 seed        seed the playground        [-Scale 1m|10m|100m] [-Force]
        .\lab.ps1 dev         run backend + frontend together
        .\lab.ps1 api         backend only
        .\lab.ps1 web         frontend only
        .\lab.ps1 reset       drop and recreate lab_data, then reseed
        .\lab.ps1 cold        restart the container for a genuinely cold run
        .\lab.ps1 psql        psql shell on lab_data
        .\lab.ps1 test        pytest + mypy + ruff + tsc
        .\lab.ps1 install     create the venv and install all dependencies
        .\lab.ps1 status      what is running, and how big the data is
        .\lab.ps1 stop        kill whatever is holding the API/Vite ports
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'seed', 'dev', 'api', 'web', 'reset', 'cold', 'psql',
                 'test', 'install', 'status', 'logs', 'stop')]
    [string]$Task = 'status',

    [ValidateSet('1m', '10m', '100m')]
    [string]$Scale = '10m',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$Root     = $PSScriptRoot
$Compose  = Join-Path $Root 'docker\docker-compose.yml'
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Python   = Join-Path $Backend '.venv\Scripts\python.exe'
$Container = 'pg-perf-lab-db'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

function Assert-Venv {
    if (-not (Test-Path $Python)) {
        throw "No virtualenv at $Python. Run: .\lab.ps1 install"
    }
}

function Assert-Docker {
    docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running. Start Docker Desktop and try again."
    }
}

function Invoke-Up {
    Assert-Docker
    Write-Step 'starting Postgres'
    docker compose -f $Compose up -d --build
    Write-Step 'waiting for the healthcheck'
    for ($i = 0; $i -lt 60; $i++) {
        $state = docker inspect -f '{{.State.Health.Status}}' $Container 2>$null
        if ($state -eq 'healthy') { Write-Host "    healthy" -ForegroundColor Green; return }
        Start-Sleep -Seconds 2
    }
    throw "Container never became healthy. Check: .\lab.ps1 logs"
}

function Invoke-Seed {
    Assert-Venv
    $seedArgs = @('-m', 'seed.seed', '--scale', $Scale)
    if ($Force) { $seedArgs += '--force' }
    Push-Location $Backend
    try { & $Python @seedArgs; if ($LASTEXITCODE -ne 0) { throw "seed failed" } }
    finally { Pop-Location }
}

switch ($Task) {

    'install' {
        Write-Step 'creating the backend virtualenv'
        python -m venv (Join-Path $Backend '.venv')
        Push-Location $Backend
        try {
            & $Python -m pip install --upgrade pip
            & $Python -m pip install -e '.[dev]'
        } finally { Pop-Location }

        Write-Step 'installing frontend packages'
        Push-Location $Frontend
        try { npm install } finally { Pop-Location }
        Write-Step 'done -- next: .\lab.ps1 up; .\lab.ps1 seed'
    }

    'up'   { Invoke-Up }

    'down' {
        Write-Step 'stopping Postgres (data volume kept)'
        docker compose -f $Compose down
    }

    'logs' { docker compose -f $Compose logs -f --tail 100 }

    'seed' { Invoke-Seed }

    'reset' {
        # The playground is disposable by design -- that is the point of keeping
        # app state in a separate database.
        Assert-Docker
        Write-Step 'dropping and recreating lab_data'
        docker exec $Container psql -U lab -d postgres -v ON_ERROR_STOP=1 `
            -c "DROP DATABASE IF EXISTS lab_data WITH (FORCE)" -c "CREATE DATABASE lab_data"
        if ($LASTEXITCODE -ne 0) { throw "could not recreate lab_data" }

        Write-Step 'reinstalling extensions'
        docker exec -i $Container psql -U lab -d lab_data -v ON_ERROR_STOP=1 -f - `
            < (Join-Path $Root 'docker\initdb\02-extensions.sql')

        $script:Force = $true
        Invoke-Seed
    }

    'cold' {
        # Postgres cannot drop the OS page cache from the inside, so a container
        # restart is the only honest way to get a genuinely cold run.
        Assert-Docker
        Write-Step 'restarting the container -- clears shared_buffers and the container page cache'
        docker compose -f $Compose restart
        Write-Warn 'The Windows host cache is untouched, so this is cold-ish, not cold.'
    }

    'psql' {
        Assert-Docker
        docker exec -it $Container psql -U lab -d lab_data
    }

    'api' {
        Assert-Venv
        Push-Location $Backend
        try { & $Python serve.py } finally { Pop-Location }
    }

    'web' {
        Push-Location $Frontend
        try { npm run dev } finally { Pop-Location }
    }

    'dev' {
        Assert-Venv
        Write-Step 'backend  -> http://127.0.0.1:8000  (new window)'
        Start-Process -FilePath $Python -ArgumentList 'serve.py' -WorkingDirectory $Backend
        Write-Step 'frontend -> http://127.0.0.1:5173'
        Push-Location $Frontend
        try { npm run dev } finally { Pop-Location }
    }

    'test' {
        Assert-Venv
        Push-Location $Backend
        try {
            Write-Step 'pytest';  & $Python -m pytest -q;      if ($LASTEXITCODE) { throw 'pytest failed' }
            Write-Step 'mypy';    & $Python -m mypy;           if ($LASTEXITCODE) { throw 'mypy failed' }
            Write-Step 'ruff';    & $Python -m ruff check .;   if ($LASTEXITCODE) { throw 'ruff failed' }
        } finally { Pop-Location }
        Push-Location $Frontend
        try {
            Write-Step 'tsc'; npx tsc -b --noEmit; if ($LASTEXITCODE) { throw 'tsc failed' }
        } finally { Pop-Location }
        Write-Host 'all checks passed' -ForegroundColor Green
    }

    'stop' {
        # Kill by *port*, not by command line. uvicorn's reloader spawns workers
        # whose command line reads "from multiprocessing.spawn import spawn_main"
        # with no mention of serve.py, so a name-based filter misses them -- and
        # an orphaned worker keeps the socket open and serves stale code.
        foreach ($port in 8000, 5173) {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if (-not $conns) { Write-Host "    port $port already free"; continue }
            foreach ($c in $conns) {
                $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Step "killing $($proc.ProcessName) ($($c.OwningProcess)) on port $port"
                    Stop-Process -Id $c.OwningProcess -Force
                } else {
                    # Dead owner, live socket: a child still holds a duplicated handle.
                    Write-Warn "port $port held by dead PID $($c.OwningProcess); hunting the child"
                    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                        Where-Object { $_.CommandLine -like "*parent_pid=$($c.OwningProcess)*" } |
                        ForEach-Object {
                            Write-Step "killing orphaned worker $($_.ProcessId)"
                            Stop-Process -Id $_.ProcessId -Force
                        }
                }
            }
        }
    }

    'status' {
        docker info --format '{{.ServerVersion}}' *> $null
        if ($LASTEXITCODE -ne 0) { Write-Warn 'Docker is not running.'; break }

        docker compose -f $Compose ps
        $state = docker inspect -f '{{.State.Health.Status}}' $Container 2>$null
        if ($state -ne 'healthy') { Write-Warn "container health: $state"; break }

        Write-Host ''
        docker exec $Container psql -U lab -d lab_data -c @'
SELECT c.relname                                       AS relation,
       to_char(c.reltuples, 'FM999,999,999')           AS est_rows,
       pg_size_pretty(pg_table_size(c.oid))            AS heap,
       pg_size_pretty(pg_indexes_size(c.oid))          AS indexes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY pg_total_relation_size(c.oid) DESC;
'@
    }
}
