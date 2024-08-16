from flask import Flask, request, jsonify, send_from_directory, render_template
import zipfile
import os
import re
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
UPLOAD_FOLDER = 'uploads'
EXTRACTED_FOLDER = 'extracted'
PROCESSED_FOLDER = 'processed'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

@app.route('/')
def upload_file1():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'})

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'})

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # Clear previous extracted files
    for filename in os.listdir(EXTRACTED_FOLDER):
        os.remove(os.path.join(EXTRACTED_FOLDER, filename))

    # Extract the ZIP file
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(EXTRACTED_FOLDER)
    except zipfile.BadZipFile:
        return jsonify({'success': False, 'message': 'Bad Zip File'})

    return jsonify({'success': True})

@app.route('/process', methods=['GET'])
def process_file():
    option = request.args.get('option')

    # Clear previous processed files
    for filename in os.listdir(PROCESSED_FOLDER):
        os.remove(os.path.join(PROCESSED_FOLDER, filename))

    # Assuming there's only one file in the extracted folder
    extracted_files = os.listdir(EXTRACTED_FOLDER)
    if not extracted_files:
        return jsonify({'success': False, 'message': 'No files found in extracted folder'})

    input_file = os.path.join(EXTRACTED_FOLDER, extracted_files[0])
    output_file = os.path.join(PROCESSED_FOLDER, f'{option}.html')

    try:
        if option == 'error':
            process_errors(input_file, output_file)
        elif option == 'queries':
            min_time = float(request.args.get('min_time', 0))
            process_queries(input_file, output_file, min_time)
        elif option == 'transaction':
            request_id = request.args.get('request_id')
            if not request_id or not process_transaction(input_file, output_file, request_id):
                return jsonify({'success': False, 'message': f'Failed to process transaction with request_id {request_id}'})
        else:
            return jsonify({'success': False, 'message': 'Invalid option'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error during processing: {e}'})

    return jsonify({'success': True, 'url': f'/download/{option}.html'})

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(PROCESSED_FOLDER, filename)





import re
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def process_errors(input_file, output_file):
    error_pattern = re.compile(r'\[ERR\]')
    delimiter_pattern = re.compile(r'^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\]')
    core_message_pattern = re.compile(r'\[ERR\]\[.*?\]\[\]\s*(.*?)(?=\s*\(Count:\s*\d+\))')

    exclude_tables = ['"Feature"."EbmsJob"', "SELECT", "AS", "FROM", "WHERE", "ORDERBY", "INSERT", "INNER", "VALUES", "ORDER", "UPDATE", "RETURNING", "LIMIT", '"Liner"."VoyageMasterDtl"', '"Global"."JobCardTypeMaster"', '"Global"."PortMaster"', '"Common"."DocSeqControlMaster"', '"Common"."DocPrefixMasterDtl"', '"Common"."LocationMaster"']

    with open(input_file, 'r', encoding='utf-8', errors='ignore') as infile:
        lines = infile.readlines()

    error_entries = []
    current_entry = []
    current_core_message = None
    is_in_error = False

    for i, line in enumerate(lines):
        line = line.strip()

        if any(table in line for table in exclude_tables):
            continue

        if error_pattern.search(line):
            if current_core_message:
                error_entries.append((current_core_message, "\n".join(current_entry)))

            match = core_message_pattern.search(line)
            if match:
                current_core_message = match.group(1).strip()
            else:
                current_core_message = line
            current_entry = [line]
            is_in_error = True
        elif is_in_error:
            if delimiter_pattern.search(line):
                error_entries.append((current_core_message, "\n".join(current_entry)))
                current_entry = []
                is_in_error = False
            else:
                current_entry.append(line)

        if i == len(lines) - 1 and current_entry:
            error_entries.append((current_core_message, "\n".join(current_entry)))

    messages = [entry[0] for entry in error_entries]
    vectorizer = TfidfVectorizer().fit_transform(messages)
    similarity_matrix = cosine_similarity(vectorizer)
    similarity_threshold = 0.3

    groups = []
    visited = [False] * len(messages)

    def group_errors(index):
        group = []
        stack = [index]
        while stack:
            idx = stack.pop()
            if visited[idx]:
                continue
            visited[idx] = True
            group.append(idx)
            for j, sim in enumerate(similarity_matrix[idx]):
                if not visited[j] and sim >= similarity_threshold:
                    stack.append(j)
        return group

    grouped_indices = []
    for i in range(len(messages)):
        if not visited[i]:
            group = group_errors(i)
            grouped_indices.append(group)

    group_counts = defaultdict(int)
    group_details = defaultdict(list)

    for group in grouped_indices:
        core_message = error_entries[group[0]][0]
        group_counts[core_message] = len(group)
        for idx in group:
            group_details[core_message].append(error_entries[idx][1])

    with open(output_file, 'w', encoding='utf-8') as file:
        file.write('<html><head>\n')
        file.write('<style>\n')
        file.write('body { font-family: Arial, sans-serif; }\n')
        file.write('h1 { color: #333; }\n')
        file.write('.error-section { margin-bottom: 20px; }\n')
        file.write('.details { display: none; margin-top: 10px; }\n')
        file.write('.toggle-button { cursor: pointer; color: #007BFF; text-decoration: underline; }\n')
        file.write('</style>\n')
        file.write('<script>\n')
        file.write('function toggleDetails(id) {\n')
        file.write('  var details = document.getElementById(id);\n')
        file.write('  if (details.style.display === "none") {\n')
        file.write('    details.style.display = "block";\n')
        file.write('  } else {\n')
        file.write('    details.style.display = "none";\n')
        file.write('  }\n')
        file.write('}\n')
        file.write('</script>\n')
        file.write('</head><body>\n')
        file.write('<h1>Error Log</h1>\n')
        for core_message, details in group_details.items():
            file.write(f'<div class="error-section">\n')
            file.write(f'<h2>{core_message}</h2>\n')
            file.write(f'<p>Count: {group_counts[core_message]}</p>\n')
            file.write(f'<p class="toggle-button" onclick="toggleDetails(\'{core_message.replace(" ", "_")}\')">Show Details</p>\n')
            file.write(f'<div id="{core_message.replace(" ", "_")}" class="details">\n')
            for detail in details:
                file.write('<pre>\n')
                file.write(detail)
                file.write('</pre>\n')
            file.write('</div>\n')
            file.write('</div>\n')
        file.write('</body></html>\n')

    print(f"Errors processed and HTML generated at: {output_file}")



import re
from collections import defaultdict

def extract_execution_time(line):
    """Extract execution time from the log line (e.g., "Executed DbCommand (82ms)")"""
    match = re.search(r'Executed DbCommand \((\d+)ms\)', line)
    if match:
        execution_time = int(match.group(1))
        return execution_time
    return None

def extract_table_names(sql_query):
    """Extract table names from SQL query"""
    print(f"Extracting tables from query: {sql_query}")  # Debug statement
    # Regex to handle table names in the format FROM "Schema"."TableName" or JOIN "Schema"."TableName"
    table_names = re.findall(r'\b(?:FROM|JOIN|UPDATE|INTO)\s+"[^"]+"\."([^"]+)"', sql_query, re.IGNORECASE)
    table_names = list(set(table_names))  # Remove duplicates
    print(f"Extracted tables: {table_names}")  # Debug statement
    return table_names

def group_queries_by_table(lines):
    table_data = defaultdict(lambda: {
        'count': 0,
        'queries': [],
        'total_time': 0.0,
        'max_time': float('-inf'),
        'min_time': float('inf')
    })

    all_times = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if 'Executed DbCommand' in line:
            execution_time = extract_execution_time(line)
            sql_query = ""

            i += 1
            while i < len(lines) and not lines[i].strip().startswith('[') and lines[i].strip() != '':
                sql_query += lines[i].strip() + " "
                i += 1

            if execution_time is not None and sql_query.strip():
                all_times.append(execution_time)
                table_names = extract_table_names(sql_query)
                if table_names:
                    for table_name in table_names:
                        table_data[table_name]['count'] += 1
                        table_data[table_name]['queries'].append(sql_query.strip())
                        table_data[table_name]['total_time'] += execution_time
                        table_data[table_name]['max_time'] = max(table_data[table_name]['max_time'], execution_time)
                        table_data[table_name]['min_time'] = min(table_data[table_name]['min_time'], execution_time)

        i += 1

    average_time = sum(all_times) / len(all_times) if all_times else 0

    for table, data in table_data.items():
        data['average_time'] = data['total_time'] / data['count'] if data['count'] > 0 else 0

    return table_data, average_time

def generate_queries_html(table_data, average_time, output_file):
    """Generate an HTML file with the grouped query data"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("<html><head>")
        f.write("<style>")
        f.write("body { font-family: Arial, sans-serif; }")
        f.write("h1 { color: #333; }")
        f.write(".table-section { margin-bottom: 20px; }")
        f.write(".queries { display: none; margin-top: 10px; }")
        f.write(".toggle-button { cursor: pointer; color: #007BFF; text-decoration: underline; }")
        f.write("</style>")
        f.write("<script>")
        f.write("function toggleQueries(id) {")
        f.write("  var queries = document.getElementById(id);")
        f.write("  if (queries.style.display === 'none') {")
        f.write("    queries.style.display = 'block';")
        f.write("  } else {")
        f.write("    queries.style.display = 'none';")
        f.write("  }")
        f.write("}")
        f.write("</script>")
        f.write("</head><body>")
        f.write("<h1>SQL Query Report</h1>")
        f.write(f"<p>Overall Average Execution Time: {average_time:.2f} ms</p>")
        for table, data in table_data.items():
            f.write(f"<div class='table-section'>")
            f.write(f"<h2>{table}</h2>")
            f.write(f"<p>Count: {data['count']}</p>")
            f.write(f"<p>Max Execution Time: {data['max_time']} ms</p>")
            f.write(f"<p>Min Execution Time: {data['min_time']} ms</p>")
            f.write(f"<p>Average Execution Time: {data['average_time']:.2f} ms</p>")
            f.write(f"<p class='toggle-button' onclick=\"toggleQueries('{table}')\">Toggle Queries</p>")
            f.write(f"<div id='{table}' class='queries'>")
            f.write("<ul>")
            for query in data['queries']:
                f.write(f"<li>{query}</li>")
            f.write("</ul>")
            f.write("</div>")
            f.write("</div>")
        f.write("</body></html>")

def process_queries(input_file, output_file, min_exec_time=None):
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as infile:
        lines = infile.readlines()

    table_data, average_time = group_queries_by_table(lines)
    
    if min_exec_time is not None:
        table_data = {table: data for table, data in table_data.items() if data['average_time'] >= min_exec_time}

    generate_queries_html(table_data, average_time, output_file)
    print(f"Queries processed and HTML generated at: {output_file}")


def process_transaction(input_file, output_file, request_id):
    section = extract_full_request_sections(input_file, request_id)
    if section:
        with open(output_file, 'w', encoding='utf-8') as file:
            file.write('<html><body>\n')
            file.write('<h1>Extracted Request Sections</h1>\n')
            file.write('<pre>\n')  # Preserve formatting
            file.write(section)
            file.write('</pre>\n')
            file.write('</body></html>')
        return True
    return False

def extract_full_request_sections(file_path, request_id):
    pattern = re.compile(
        rf'===BEGIN REQUEST===\s*{re.escape(request_id)}\s*.*?===END REQUEST===\s*{re.escape(request_id)}',
        re.DOTALL
    )

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        content = file.read()

    matches = pattern.findall(content)
    return "\n\n".join(matches).strip()

def generate_html(section, output_file):
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write('<html><body>\n')
        file.write('<h1>Extracted Request Sections</h1>\n')
        file.write('<pre>\n')  # Preserve formatting
        file.write(section)
        file.write('</pre>\n')
        file.write('</body></html>')


if __name__ == '__main__':
    app.run(host='0.0.0.0',debug=True)
