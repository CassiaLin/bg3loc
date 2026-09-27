# Archive Backend v1 / Archive Backend v1

## English

This milestone verifies and implements read-only PAK listing through LSLib Divine.

Verified upstream command contract:

```text
Divine.exe -a list-package -g bg3 -s <package> -x <glob>
```

or, for the .NET CLI form:

```text
dotnet Divine.dll -a list-package -g bg3 -s <package> -x <glob>
```

Verified output format from LSLib `CommandLinePackageProcessor.ListPackageFiles()`:

```text
<entry-path>\t<size>\t<crc>
```

BG3Loc uses `*.loca` during `scan` so that the scan manifest records actual LOCA archive entries without extracting the package.

Failures are fail-closed: non-zero subprocess exit status, malformed output, or inability to execute the backend are reported as warnings/errors and are never treated as a successful archive listing.

This milestone does not yet implement extraction or LOCA conversion.

## 繁體中文

本里程碑正式驗證並實作透過 LSLib Divine 以唯讀方式列出 PAK 內容。

已驗證的上游 CLI contract：

```text
Divine.exe -a list-package -g bg3 -s <package> -x <glob>
```

.NET CLI 形式則為：

```text
dotnet Divine.dll -a list-package -g bg3 -s <package> -x <glob>
```

LSLib `CommandLinePackageProcessor.ListPackageFiles()` 已確認輸出格式為：

```text
<entry-path>\t<size>\t<crc>
```

BG3Loc 在 `scan` 階段使用 `*.loca`，因此不需解包整個 PAK，就能把實際 LOCA archive entry 寫進 scan manifest。

失敗時採 fail-closed：subprocess 非零結束碼、輸出格式異常、backend 無法執行，都只會回報 warning/error，不會被當成成功 listing。

本里程碑尚不處理 extract 或 LOCA conversion。
