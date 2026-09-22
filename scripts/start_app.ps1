$ErrorActionPreference = "Stop"

$ports = @(8080, 8081, 8082, 8501, 8502, 8503, 8504, 8505)
foreach ($port in $ports) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction Stop
        foreach ($conn in $connections) {
            if ($conn.OwningProcess) {
                Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }
    catch {
    }
}

Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$PSScriptRoot/..'; python -m uvicorn ecommerce_assistant.api.service:app --host 0.0.0.0 --port 8082" 
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$PSScriptRoot/..'; `$env:API_BASE_URL='http://localhost:8082'; python -m streamlit run src/ecommerce_assistant/streamlit_app.py --server.port 8505 --server.address 0.0.0.0" 

Write-Host "已清理旧端口并启动后端与前端。"
Write-Host "后端: http://localhost:8082"
Write-Host "前端: http://localhost:8505"
