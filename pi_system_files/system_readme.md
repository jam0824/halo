# サービスを置く場所
```
/etc/systemd/system/
```

# 起動確認
```
sudo systemctl daemon-reload
sudo systemctl enable halo.service      # 次回起動時に自動実行
sudo systemctl start halo.service       # いま試しに実行
sudo systemctl status halo.service      # 状態確認
```

# ログの確認
```
journalctl -u halo.service -e
```