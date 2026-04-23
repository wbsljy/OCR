# 沖壓 - 鍛壓
base_table_1 ="""
<table>
  <tr>
    <td rowspan="2">製程</td>
    <td>原材批次</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2" rowspan="2">匯總</td>
  </tr>
  <tr>
    <td>線別/標號</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td rowspan="15">沖壓</td>
    <td>投入數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>良品數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>不良數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>實際良率</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>目標良率</td>
    <td colspan="2">99.80%</td>
    <td colspan="2">99.80%</td>
    <td colspan="2">99.80%</td>
    <td colspan="2">99.80%</td>
    <td colspan="2">99.80%</td>
  </tr>
  <tr>
    <td>不良項目</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
  </tr>
  <tr>
    <td>5.0+1.0/-0.3偏小</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>50+12/-3偏小</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>50+12/-3偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>垂直度0.40偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>垂直度0.70偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>4.20+/-0.30|P1-P3|<0.2偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>4.20+/-0.30|P2-P4|<0.2偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>2D碼偏位</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>DDS</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>
"""

# 沖壓 - 固熔（僅三組線體 + 匯總，無原材批次）
base_table_2 = """
<table>
  <tr>
    <td>製程</td>
    <td>線別</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2">匯總</td>
  </tr>
  <tr>
    <td rowspan="9">沖壓</td>
    <td>投入數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>良品數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>不良數</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>實際良率</td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>目標良率</td>
    <td colspan="2">100%</td>
    <td colspan="2">100%</td>
    <td colspan="2">100%</td>
    <td colspan="2">100%</td>
  </tr>
  <tr>
    <td>不良項目</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
    <td>不良數</td>
    <td>不良率</td>
  </tr>
  <tr>
    <td>硬度40≤Hba≤60偏大</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>變形</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>DDS</td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>
"""

# 沖壓 - 時效
base_table_3 = """
<table>
  <tr>
    <td rowspan="2">製程</td>
    <td>投入數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>良品數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td rowspan="8">沖壓</td>
    <td>不良數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>實際良率</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>目標良率</td>
    <td colspan="2">100.00%</td>
  </tr>
  <tr>
    <td>不良項目</td>
    <td>不良數</td>
    <td>不良率</td>
  </tr>
  <tr>
    <td>變形</td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>機械性能送檢</td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>硬度Hba≥74偏小</td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>DDS</td>
    <td></td>
    <td></td>
  </tr>
</table>
"""

# 金加 - CNC0
base_table_4 = """
<table>
  <tr>
    <td rowspan="2">製程</td>
    <td>投入數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>抽檢數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td rowspan="17">金加</td>
    <td>一次良品數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>不良數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>可重工不良數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>不可重工不良數</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>一次良率</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>二次良率</td>
    <td colspan="3"></td>
  </tr>
  <tr>
    <td>一次良率目標</td>
    <td colspan="3">99.70%</td>
  </tr>
  <tr>
    <td>二次良率目標</td>
    <td colspan="3">100.00%</td>
  </tr>
  <tr>
    <td>不良項目</td>
    <td>可重工</td>
    <td>不可重工</td>
    <td>不良率</td>
  </tr>
  <tr>
    <td>DDS</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>臺階/過切</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>毛邊/毛刺</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>大平面未見光</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>大平面刀紋/刀痕</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>平面度0.10偏大</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>4.70+/-0.10偏大</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>4.70+/-0.10偏小</td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>
"""

# 金加 - CNC0 全檢 
base_table_5 = """
<table>
  <tr>
    <td rowspan="2">製程</td>
    <td>投入數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>一次良品數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td rowspan="11">金加</td>
    <td>不良數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>可重工不良數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>不可重工不良數</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>一次良率</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>二次良率</td>
    <td colspan="2"></td>
  </tr>
  <tr>
    <td>一次良率目標</td>
    <td colspan="2">99.90%</td>
  </tr>
  <tr>
    <td>二次良率目標</td>
    <td colspan="2">100%</td>
  </tr>
  <tr>
    <td>不良項目</td>
    <td>不良數</td>
    <td>不良率</td>
  </tr>
  <tr>
    <td>大平面刀紋/刀痕</td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>毛邊</td>
    <td></td>
    <td></td>
  </tr>
  <tr>
    <td>大平面未見光</td>
    <td></td>
    <td></td>
  </tr>
</table>
"""
