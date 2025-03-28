
import numpy as np
import pandas as pd
import re
from collections import defaultdict
from underthesea import word_tokenize
from xgboost import XGBClassifier
import random
import re
from underthesea import word_tokenize
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.multioutput import MultiOutputClassifier


# df_dl=pd.read_excel('du_lieu_mau_50k.xlsx')
# Đọc hai file Excel
df1 = pd.read_excel("du_lieu_mau_550k_1.xlsx")
df2 = pd.read_excel("du_lieu_mau_550k_2.xlsx")

# Ghép hai dataframe lại với nhau
df_dl = pd.concat([df1, df2], ignore_index=True)

df_result=df_dl[['Product List','label']]
df_result=pd.DataFrame(df_result)
df_result

# Tokenize text
vocab_size =180000
window_size = 2  # Number of words before & after target word
embedding_dim = 150
df_result["Tokenized"] = df_result["Product List"].apply(lambda x: word_tokenize(x, format="text").split())

# Build vocabulary
word_counts = defaultdict(int)
for tokens in df_result["Tokenized"]:
    for word in tokens:
        word_counts[word] += 1

# Assign indices to words
vocab = list(word_counts.keys())[:vocab_size]
word_to_index = {word: i for i, word in enumerate(vocab)}

# Initialize co-occurrence matrix
co_occurrence_matrix = np.zeros((len(vocab), len(vocab)), dtype=np.int16)

# Populate the co-occurrence matrix
for tokens in df_result["Tokenized"]:
    token_indices = [word_to_index[word] for word in tokens if word in word_to_index]
    for idx, word_idx in enumerate(token_indices):
        left_context = token_indices[max(0, idx - window_size): idx]
        right_context = token_indices[idx + 1: idx + 1 + window_size]
        context = left_context + right_context
        for context_idx in context:
            co_occurrence_matrix[word_idx, context_idx] += 1  # Count occurrences

co_occurrence_matrix

#SGD ,mini batch
import numpy as np

# Define the weighting function
X_max = 100  # Threshold
alpha = 0.75

def f(X_ij):
    return (X_ij / (X_max + 1e-8)) ** alpha if X_ij < X_max else 1

# Hyperparameters
learning_rate = 0.01  # Start with a higher LR, then decay
num_epochs = 50
batch_size = 1000  # Mini-batch size
decay_factor = 0.99  # Learning rate decay
clip_value = 5  # Gradient clipping

# Initialize embeddings
vocab_size = len(vocab)
word_embeddings = np.random.uniform(-0.5, 0.5, (vocab_size, embedding_dim))
context_embeddings = np.random.uniform(-0.5, 0.5, (vocab_size, embedding_dim))

nonzero_pairs = np.array([(int(i), int(j), float(co_occurrence_matrix[i, j]))
                          for i in range(vocab_size)
                          for j in range(vocab_size) if co_occurrence_matrix[i, j] > 0], dtype=object)


# Training loop with SGD
for epoch in range(num_epochs):
    np.random.shuffle(nonzero_pairs)  # Shuffle dataset each epoch
    total_loss = 0

    for batch_start in range(0, len(nonzero_pairs), batch_size):
        batch = nonzero_pairs[batch_start: batch_start + batch_size]

        for i, j, X_ij in batch:
            weight = f(X_ij)
            dot_product = np.dot(word_embeddings[i], context_embeddings[j])

            # Loss function
            loss = weight * ((dot_product - np.log(X_ij + 1e-8)) ** 2)
            total_loss += loss

            # Compute gradients
            grad_u = 2 * weight * (dot_product - np.log(X_ij + 1e-8)) * context_embeddings[j]
            grad_v = 2 * weight * (dot_product - np.log(X_ij + 1e-8)) * word_embeddings[i]

            # Gradient clipping
            grad_u = np.clip(grad_u, -clip_value, clip_value)
            grad_v = np.clip(grad_v, -clip_value, clip_value)

            # SGD Updates
            word_embeddings[i] -= learning_rate * grad_u
            context_embeddings[j] -= learning_rate * grad_v

    # Decay learning rate
    learning_rate *= decay_factor

    if epoch % 10 == 0:
        print(f"Epoch {epoch}, Loss: {total_loss:.4f}, Learning Rate: {learning_rate:.6f}")

# Merge embeddings
final_embeddings = word_embeddings + context_embeddings

# Normalize embeddings
final_embeddings /= (np.linalg.norm(final_embeddings, axis=1, keepdims=True) + 1e-8)

# Create word embedding dictionary
word_embedding_dict = {word: final_embeddings[i] for word, i in word_to_index.items()}

# Apply embeddings to dataset
one_hot_encoder = OneHotEncoder(sparse_output=False)
df_result["Encoded_Label"] = list(one_hot_encoder.fit_transform(df_result["label"].values.reshape(-1, 1)))
def sentence_to_vector(sentence, embedding_dict):
    word_vectors = [embedding_dict[word] for word in sentence if word in embedding_dict]
    return np.mean(word_vectors, axis=0) if word_vectors else np.zeros(embedding_dim)

df_result["Embedding"] = df_result["Tokenized"].apply(lambda x: sentence_to_vector(x, word_embedding_dict))


X_train, X_test, y_train, y_test, train_indices, test_indices = train_test_split(
    np.vstack(df_result["Embedding"].values),
    np.vstack(df_result["Encoded_Label"].values),
    df_result.index,  # Track original indices
    test_size=0.2,
    shuffle=True
)

# Store test indices
X_test_indices = test_indices

xgb_classifier = XGBClassifier(
    use_label_encoder=False,
    eval_metric='logloss',
    objective="binary:logistic",  # Suitable for multi-label tasks
    booster='gbtree',  # Better decision-making
    n_estimators=500,  # Increased number of boosting rounds
    learning_rate=0.05,  # Slower learning for better generalization
    max_depth=6,  # Increase tree depth
    subsample=0.8,  # Reduce overfitting
    colsample_bytree=0.8  # Feature sampling
)
classifier = MultiOutputClassifier(xgb_classifier)
classifier.fit(X_train, y_train)
# Train a multi-label classifier
#classifier = MultiOutputClassifier(LogisticRegression(multi_class='ovr', solver='lbfgs', max_iter=10000))

#classifier.fit(X_train, y_train)

# Predict and evaluate
y_pred_proba = np.array([clf.predict_proba(X_test)[:, 1] for clf in classifier.estimators_]).T  # Fix Shape Issue
threshold = 0.5
y_pred = (y_pred_proba >= threshold).astype(int)  # Apply threshold
print("y_test shape:", y_test.shape)
print("y_pred shape:", y_pred.shape)

accuracy = accuracy_score(y_test, y_pred)
print(f"Classification Accuracy: {accuracy:.2f}")

import joblib

# Lưu mô hình vào file .pkl
joblib.dump(classifier, 'model_550k_v2.pkl')
print("Mô hình đã được lưu thành công!")

# def predict_new_test_set(df):
#     df_new_test = df
#     # Tokenize & Convert to Embeddings
#     df_new_test["Tokenized"] = df_new_test["Product List"].apply(lambda x: word_tokenize(x, format="text").split())

#     df_new_test["Embedding"] = df_new_test["Tokenized"].apply(lambda x: sentence_to_vector(x, word_embedding_dict))

#     X_new_test = np.vstack(df_new_test["Embedding"].values)

#     # Predict Sentiment Labels
#     y_pred_proba_new = np.array([clf.predict_proba(X_new_test)[:, 1] for clf in classifier.estimators_]).T
#     y_pred_new = (y_pred_proba_new >= threshold).astype(int)

#     # Decode Labels
#     y_pred_labels = []
#     for row in y_pred_new:
#         if row.sum() == 0:  # If all values are zero, assign "Unknown"
#             y_pred_labels.append(["Unknown"])
#         else:
#             y_pred_labels.append(one_hot_encoder.inverse_transform(row.reshape(1, -1))[0])

# # Convert to a NumPy array
#     y_pred_labels = np.array(y_pred_labels).flatten()
#     df_new_test['Predict_Label'] = y_pred_labels  # Assign predicted labels

#     return df_new_test[["Product List", "Predict_Label"]]

# df_dl2=pd.read_excel('du_lieu_mau_50k.xlsx')
# df_result_final=df_dl2[['Product List']]
# df_result_final=pd.DataFrame(df_result_final)
# df_result_final

# pred_new_test = predict_new_test_set(df_result_final)
# pred_new_test

# Convert predicted one-hot encoded labels back to original label names
y_pred_labels = []
for row in y_pred:
    if row.sum() == 0:  # If all values are zero, assign "Unknown"
        y_pred_labels.append(["Unknown"])
    else:
        y_pred_labels.append(one_hot_encoder.inverse_transform(row.reshape(1, -1))[0])

# Convert to a NumPy array
y_pred_labels = np.array(y_pred_labels).flatten()
y_pred_labels

df_X_test = df_result.loc[X_test_indices, ['Product List']].copy()
df_X_test['predict_label'] = y_pred_labels  # Assign predicted labels

df_X_test

import json
# Chuyển đổi mảng numpy thành danh sách để lưu được vào JSON
def save_to_json(data, filename):
    with open(filename, "w") as f:
        json.dump({key: value.tolist() for key, value in data.items()}, f)

# Lưu dictionary vào file JSON
save_to_json(word_embedding_dict, "word_embeddings_550k_v2.json")
