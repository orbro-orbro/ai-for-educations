$ErrorActionPreference='Stop'
& docker version --format '{{.Client.Version}} / {{.Server.Version}}'
if($LASTEXITCODE -ne 0) { throw 'Docker unavailable' }
& docker compose version
& node -p 'JSON.stringify({host_node:process.version})'
if($LASTEXITCODE -ne 0) { throw 'Host Node version inspection failed' }
& npm.cmd --version
if($LASTEXITCODE -ne 0) { throw 'Host npm version inspection failed' }
foreach($taskName in @('postgres','api','web','runner-controller')) {
    & docker inspect ('knowbound-wave4-demo-'+$taskName+'-1') --format '{{.Name}} image={{.Image}} status={{.State.Status}} health={{.State.Health.Status}}'
    if($LASTEXITCODE -ne 0) { throw 'Demo runtime inspection failed' }
}
& docker exec knowbound-wave4-demo-api-1 python -c 'import sys,importlib.metadata as m; print(sys.version); print({n:m.version(n) for n in ("fastapi","pydantic","SQLAlchemy","alembic","psycopg","uvicorn")})'
if($LASTEXITCODE -ne 0) { throw 'API version inspection failed' }
& docker exec knowbound-wave4-demo-web-1 node --version
& docker exec knowbound-wave4-demo-web-1 npm --version
& docker exec knowbound-wave4-demo-postgres-1 psql -U knowbound -d wave4_demo -Atc "SELECT version(); SELECT name,default_version,installed_version FROM pg_available_extensions WHERE name='vector'; SELECT version_num FROM alembic_version"
if($LASTEXITCODE -ne 0) { throw 'Read-only database version inspection failed' }
& docker run --rm --network none --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 64 --memory 512m --cpus 1 --tmpfs '/work:rw,nosuid,nodev,exec,size=64m,mode=0700,uid=10001,gid=10001' --entrypoint sh knowbound-wave4-demo-sandbox:task11 -c 'cjc -v && cjpm -v'
if($LASTEXITCODE -ne 0) { throw 'Isolated toolchain version inspection failed' }
