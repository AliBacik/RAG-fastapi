import os
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

response = (
    supabase.schema("eternate").table("intent_events").select("customer_message,gemini_intent").execute()
)

# TODO 1: response.data'yi pandas DataFrame'e cevir (df degiskenine ata)
df = pd.DataFrame(response.data)

# TODO 2: df.head() ile ilk birkac satiri yazdir
print(df.head())

# TODO 3: "gemini_intent" kolonunun deger dagilimini yazdir (adet)
# ipucu: value_counts()
print(df["gemini_intent"].value_counts())


# TODO 4: ayni dagilimi yuzde olarak yazdir
# ipucu: value_counts(normalize=True)
print(df["gemini_intent"].value_counts(normalize=True))

# TODO 5: her kolonda kac tane eksik (NaN) deger oldugunu yazdir
# ipucu: isna().sum()
print(df.isna().sum())

# TODO 6: "customer_message" kolonunda bos string ("") olan satir sayisini bul
# ipucu: str.strip().eq("")
print(df["customer_message"].str.strip().eq("").sum())


# TODO 7: yeni bir kolon olustur: "mesaj_uzunlugu" (her mesajin karakter sayisi)
# ipucu: str.len()
df["mesaj_uzunlugu"]=df["customer_message"].str.len()

# TODO 8: mesaj_uzunlugu icin describe() ile istatistik ozet yazdir
print(df["mesaj_uzunlugu"].describe())


# TODO 9: her intent icin ortalama mesaj uzunlugunu bul, buyukten kucuge sirala
# ipucu: groupby("gemini_intent")["mesaj_uzunlugu"].mean().sort_values(...)
print(df.groupby("gemini_intent")["mesaj_uzunlugu"].mean().sort_values(ascending=False))

# TODO 10: en uzun 3 ve en kisa 3 mesaji (intent ve uzunluk kolonlariyla) yazdir
# ipucu: nlargest() / nsmallest()
print(df.nlargest(3,"mesaj_uzunlugu") [["gemini_intent","mesaj_uzunlugu"]])
print(df.nsmallest(3,"mesaj_uzunlugu") [["gemini_intent","mesaj_uzunlugu"]])

