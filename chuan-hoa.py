import pandas as pd

# Đọc file csv gốc
df = pd.read_csv("alonhadat_data.csv")

# Loại bỏ các hàng có cột 'error' khác rỗng
df = df[df["error"].isna() | (df["error"].astype(str).str.strip() == "")]

# Xóa cột 'error'
df = df.drop(columns=["error"])

# Xuất ra file mới
df.to_csv("alonhadat_data_clean.csv", index=False, encoding="utf-8-sig")