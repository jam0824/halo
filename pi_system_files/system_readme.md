# サービスを置く場所
```
/etc/systemd/system/
```

# 環境ファイルを作成する
環境ファイルを作成（例 /etc/default/halo）
```
# 引用符なしで書きます
OPENAI_API_KEY=sk-xxxx
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

# serviceの修正時
```
sudo systemctl daemon-reload
sudo systemctl restart halo.service
```

# serviceを止めたいとき
```
sudo systemctl stop halo.service
```
自動起動を止めたい場合
```
sudo systemctl disable halo
```


# ユーザーサービス化するなら以下（今はしていない）
ユーザーセッションの PulseAudio に確実に乗ります。
```
mkdir -p /home/pi/.config/systemd/user
cp /etc/systemd/system/halo.service /home/pi/.config/systemd/user/halo.service
# 中身は User= 行を消し、WantedBy=default.target に変更（他は同等）
systemctl --user daemon-reload
systemctl --user enable --now halo.service
sudo loginctl enable-linger pi  # ブート時にユーザーサービス起動
```

# ユーザーサービスで動かしていて止めたい場合
```
systemctl --user stop halo.service
systemctl --user disable halo.service
```