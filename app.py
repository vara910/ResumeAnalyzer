from flask import Flask, request, render_template
import os
from werkzeug.utils import secure_filename
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from utils import extract_text

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'

# Ensure the upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def preprocess_text(text):
    # Implement your text preprocessing here (e.g., using spaCy or nltk)
    return text  # Placeholder

def calculate_similarity(resume_text, job_description):
    documents = [resume_text, job_description]
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(documents)
    return cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

@app.route('/', methods=['GET', 'POST'])
def upload_files():
    if request.method == 'POST':
        job_description = request.form['job_description']
        processed_job_description = preprocess_text(job_description)
        files = request.files.getlist('files')
        results = []

        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                resume_text = preprocess_text(extract_text(file_path))  # Implement your extract_text function
                score = calculate_similarity(resume_text, processed_job_description)
                results.append((filename, score))

        # Sort results based on score in descending order
        results.sort(key=lambda x: x[1], reverse=True)
        best_match = results[0] if results else None
        return render_template('upload.html', messages=[f"{filename}: Score {score:.2f}" for filename, score in results], best_match=best_match)
    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True)
