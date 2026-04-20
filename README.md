# QuietBJ 模块化版本（扁平结构）

这是一个面向北京住宅噪音评分的 Streamlit 原型，采用：

- 小区基础分
- 分区修正
- 高德地址归一化（输入提示 / 地理编码 / 逆地理编码）

## 文件说明

- `app.py`：页面与交互
- `community_engine.py`：小区基础分引擎
- `zone_engine.py`：分区修正引擎
- `building_engine.py`：楼栋级占位引擎
- `score_pipeline.py`：总调度器
- `amap_provider.py`：高德接口封装
- `community_repository.py`：小区数据读取与匹配
- `zone_repository.py`：分区数据读取
- `communities.csv`：小区主表
- `community_zones.csv`：小区分区修正表

## 运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 高德 Key

本地可创建 `.streamlit/secrets.toml`，内容参考 `SECRETS_EXAMPLE.toml`。

部署到 Streamlit Cloud 时，把同样内容粘贴到 Secrets 面板即可。
