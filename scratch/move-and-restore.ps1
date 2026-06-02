# scratch/move-and-restore.ps1

$NEW_DIR = "C:\Home\熊本旅遊實作\日本東西行軍路線"

# 1. 建立新資料夾結構
New-Item -Path "$NEW_DIR\conductor" -ItemType Directory -Force
New-Item -Path "$NEW_DIR\src" -ItemType Directory -Force
New-Item -Path "$NEW_DIR\knowledge\templates" -ItemType Directory -Force

# 2. 將新定錨之文件移至「日本東西行軍路線」中
Move-Item -Path "conductor\context.md" -Destination "$NEW_DIR\conductor\context.md" -Force
Move-Item -Path "conductor\doc-tracks.md" -Destination "$NEW_DIR\conductor\doc-tracks.md" -Force
Move-Item -Path "conductor\progress_report.md" -Destination "$NEW_DIR\conductor\progress_report.md" -Force
Move-Item -Path "conductor\splitting-plan.md" -Destination "$NEW_DIR\conductor\splitting-plan.md" -Force
Move-Item -Path "knowledge\templates\travel-manual-schema.md" -Destination "$NEW_DIR\knowledge\templates\travel-manual-schema.md" -Force

# 3. 將剛建立的 13 個新行程空白檔案移至新資料夾的 src 下
Move-Item -Path "src\*" -Destination "$NEW_DIR\src" -Force

# 4. 透過 git restore 還原根目錄原本的熊本行程檔案與看板
git restore src/
git restore conductor/
git restore knowledge/templates/

Write-Host "Migration and restoration complete!"
