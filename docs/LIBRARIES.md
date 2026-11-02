# Libraries (do not vendor)

| Role | Path |
|------|------|
| Arsenal | `H:\New_VLibs\v4` |
| Product host | `G:\Amy` (`pip install -e .`) |
| Product config | `G:\Amy\config\hive.yaml` |
| Runtime | `G:\HiveSTEAM` |

Amy **imports** PyHive host APIs (`WakeDaemon`, `VoiceSession`, `AssistantShell`). Source stays on H:.

```powershell
.\scripts\bootstrap.ps1
.\scripts\run.ps1
.\scripts\run.ps1 -Lan
```
