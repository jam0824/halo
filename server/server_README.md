
# nginxの設定は以下に保存
```
/etc/nginx/conf.d/voicevox.conf
```

# univcornの自動起動
`halo-api.service` に記載


# univcornのservice確認
```
sudo systemctl daemon-reload
sudo systemctl restart halo-api
sudo systemctl status halo-api --no-pager
journalctl -u halo-api -n 100 --no-pager
```

# server.py更新時
```
sudo systemctl restart halo-api
```

# make_fake_memory.pyの起動
`/etc/halo.env` に記載

# 権限設定
```
sudo chmod 600 /etc/halo.env
sudo chown root:root /etc/halo.env
```

# make_fake_memory.py実行のsystemd service
`/etc/systemd/system/halo-fakemem.service`

# 上記をタイマーで動かす
`/etc/systemd/system/halo-fakemem.timer`

# 確認
```
sudo systemctl daemon-reload
sudo systemctl enable --now halo-fakemem.timer

# 次回実行予定を確認
systemctl list-timers | grep halo-fakemem

# 手動テスト（今すぐ実行）
sudo systemctl start halo-fakemem.service

# ログ確認
journalctl -u halo-fakemem -n 50 --no-pager
```