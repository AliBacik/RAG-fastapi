import os
import pickle
import numpy as np
from dotenv import load_dotenv
from supabase import create_client
import json

from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.metrics import classification_report , confusion_matrix

import xgboost as xgb


load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

# PostgREST limitsiz select'lerde sunucu tarafinda 1000 satirda kesiyor
# (db-max-rows). Hata vermedigi icin egitim sessizce eksik veriyle
# calisiyordu; tum kayitlari almak icin sayfalama sart.
PAGE_SIZE = 1000

rows = []
start = 0

while True:
    page = (
        supabase.schema("eternate").table("intent_events")
        .select("customer_message, gemini_intent")
        .range(start, start + PAGE_SIZE - 1)
        .execute()
    )

    rows.extend(page.data)

    if len(page.data) < PAGE_SIZE:
        break

    start += PAGE_SIZE

expected = (
    supabase.schema("eternate").table("intent_events")
    .select("customer_message", count="exact")
    .limit(1)
    .execute()
).count

if expected is not None and len(rows) != expected:
    raise RuntimeError(
        f"Eksik veri cekildi: {len(rows)} satir alindi, tabloda {expected} var."
    )

print(f"Veritabanindan cekilen toplam satir: {len(rows)}")


texts=[]
labels=[]

for row in rows:
    message = row.get("customer_message")
    intent = row.get("gemini_intent")
    if not message or not intent:
        continue
    
    texts.append(message)
    labels.append(intent)
    
print(f"Toplam kullanılabilir kayıt: {len(texts)}")


label_encoder = LabelEncoder()
y= label_encoder.fit_transform(labels)

X_train_text, X_test_text, y_train, y_test= train_test_split(
    texts,y,
    test_size=0.2,
    random_state=42,
    stratify=y,
)

vectorizer = TfidfVectorizer(
    ngram_range=(1,2),
    min_df=2,
    max_features=3000,
    sublinear_tf=True,
)

X_train = vectorizer.fit_transform(X_train_text)
X_test = vectorizer.transform(X_test_text)


sample_weights = compute_sample_weight(class_weight="balanced",y=y_train)

model=xgb.XGBClassifier(
    objective="multi:softprob",
    num_class=len(label_encoder.classes_),
    eval_metric="mlogloss",
    max_depth=4,
    n_estimators=200,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    early_stopping_rounds=20,
)

model.fit(
    X_train, y_train,
    sample_weight=sample_weights,
    eval_set=[(X_test,y_test)],
    verbose=False,
)

y_pred = model.predict(X_test)

print(classification_report(
    y_test, y_pred,
    target_names=label_encoder.classes_,
))
print(confusion_matrix(y_test, y_pred))

os.makedirs("intent_ml/model_artifacts",exist_ok=True)

model.save_model("intent_ml/model_artifacts/xgb_model.json")

with open("intent_ml/model_artifacts/tfidf_vectorizer.pkl", "wb") as f:
    pickle.dump(vectorizer, f)

with open("intent_ml/model_artifacts/label_encoder.pkl", "wb") as f:
    pickle.dump(label_encoder, f)