# QuietBJ Building-Level Calculation + Background Fix

这一版解决两个问题：

1. **背景图片不显示**：改成更稳的 base64 固定背景层。
2. **楼栋级计算**：
   - 小区匹配时会先去掉楼号/单元号，用于命中小区。
   - 但周边噪音点计算会尽量保留完整输入，去高德拿更接近楼栋的坐标。
   - 再用这个楼栋点去测最近高速/主干路、学校、医院、商业/底商、餐饮、轨道交通的距离。

## 当前模型

最终静噪分 = 默认基础分 75 + 分区修正 + 建筑加分 - 密度惩罚 - 周边噪音点惩罚

## 文件

- `app.py`
- `config.py`
- `text_match.py`
- `community_repository.py`
- `zone_repository.py`
- `amap_provider.py`
- `score_engine.py`
- `noise_point_engine.py`
- `communities.csv`
- `community_zones.csv`
- `background.jpg`
- `requirements.txt`
- `SECRETS_EXAMPLE.toml`
