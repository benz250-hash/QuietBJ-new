# QuietBJ

这是修好的扁平版项目，适合直接上传到 GitHub 和 Streamlit Community Cloud。

## 这版修了什么
- 背景图改成更稳的固定背景层，不再使用 `.stApp::before` / `.stApp::after` 伪元素。
- 保留 HowLoud 风格的中间搜索框布局。
- 保留本地样本库 + 高德在线估算兜底。
- `新龙城` 已包含在样本库中。
- 所有文件都在同一层，解压后可直接上传。

## 文件
- `app.py`
- `background.jpg`
- `communities_sample.csv`
- `requirements.txt`
- `README.md`
- `SECRETS_EXAMPLE.toml`

## 本地运行
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud Secrets
```toml
AMAP_API_KEY = "你的高德 Key"
```

## 说明
- 当前仍然是地址级 / 小区级估算，不是官方实测分贝。
- 若要进一步提高准确度，下一步建议做楼栋级修正。
