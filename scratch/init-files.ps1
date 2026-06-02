# scratch/init-files.ps1

$files = @(
    '01_Chapter1_核心戰報與財務預算.md',
    '02_Day1_抵達羽田與橫濱弄髮.md',
    '03_Day2_橫濱漫遊與秋葉原模型.md',
    '04_Day3_深入東北石卷探險.md',
    '05_Day4_陸奧弘前煙火大會.md',
    '06_Day5_特急津輕秋田朝聖.md',
    '07_Day6_直飛名古屋與大須逛街.md',
    '08_Day7_名古屋城與久屋大通.md',
    '09_Day8_清晨移防廣島市區遊.md',
    '10_Day9_宮島嚴島神社海上鳥居.md',
    '11_Day10_聖地宮島SA皮克敏冒險.md',
    '12_Day11_廣島飛羽田與狂熱演唱會.md',
    '13_Day12_羽田機場最後血拼與返台.md'
)

if (-not (Test-Path "src")) {
    New-Item -Path "src" -ItemType Directory -Force
}

foreach ($f in $files) {
    $filePath = Join-Path "src" $f
    New-Item -Path $filePath -ItemType File -Force
    Write-Host "Created $filePath"
}
