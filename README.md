# Ruawd LiveContainer Source

自动跟踪以下项目 GitHub Releases 中的最新稳定 IPA：

- [FluxDO](https://github.com/Lingyan000/fluxdo)
- [Jasmine](https://github.com/ComicSparks/jasmine)
- [Pikapika](https://github.com/ComicSparks/pikapika)
- [Asspp](https://github.com/Lakr233/Asspp)
- [Kazumi](https://github.com/Predidit/Kazumi)
- [SyncClipboard](https://github.com/Ruawd/SyncClipboard-iOS)
- [Orange Cloud](https://github.com/Ruawd/orange-cloud)
- [KMusic（歌一刀）](https://github.com/Mac-XK/KMusic)
- [LK](https://github.com/Ruawd/livecontainer_source/releases/tag/lk-0.11.51)

## 添加软件源

在 LiveContainer 的“软件源”页面添加：

```text
https://raw.githubusercontent.com/Ruawd/livecontainer_source/main/apps.json
```

## 自动更新

GitHub Actions 每 15 分钟检查一次上游 Release。发现新的稳定 IPA 后，会读取 IPA
内的版本号、Bundle ID、最低系统版本和应用图标，更新 `apps.json` 并自动提交。

也可以在仓库的 Actions 页面手动运行 `Update LiveContainer source`。

本地更新命令：

```bash
python scripts/update_source.py
```

本仓库只提供软件源索引，IPA 文件直接来自各上游项目的 GitHub Release。
