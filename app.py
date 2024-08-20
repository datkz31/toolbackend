from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import os
import json
from openai import OpenAI

app = Flask(__name__)

CORS(app)

openai_key = os.getenv("sk-proj-4h6HNYfS7P9N80i2YlKXT3BlbkFJKJ7NsTzMZg4DsdZuV2p5")
client = OpenAI(api_key="sk-proj-4h6HNYfS7P9N80i2YlKXT3BlbkFJKJ7NsTzMZg4DsdZuV2p5")
{
    "error": "Error code: 400 - {'error': {'message': \"Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.\", 'type': 'invalid_request_error', 'param': 'messages.[2].role', 'code': None}}"
}
# Kết nối cơ sở dữ liệu PostgreSQL
def get_database_connection():
    return psycopg2.connect(
        dbname="captone",
        user="postgres",
        password="ductien31072004",
        host="localhost",
        port="5432"
    )

# Hàm truy vấn cơ sở dữ liệu
def ask_database(conn, query):
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = str(cursor.fetchall())
    except Exception as e:
        results = f"Query failed with error: {e}"
    return results

# Tạo tin nhắn cho OpenAI
def create_openai_messages(user_query):
    database_schema_string = create_database_schema_string()
    return [
        {
            "role": "system",
            "content": """Bạn là một người trực tổng đài dịch vụ tour du lịch. Nhiệm vụ của bạn là trả lời các câu hỏi
            của khách hàng dựa vào thông tin được cung cấp trong các bảng dữ liệu liên quan đến du lịch bao gồm: tours, 
            shelter, destination, ticket. Luôn trả lời với sự lịch thiệp và chuyên nghiệp. Mọi câu trả lời chỉ được xoay
            quanh về thông tin của tour du lịch bao gồm thông tin vé, giá vé cụ thể và ngày giờ khởi hành kết thúc và chỗ
            ở trong thời gian du lịch của tour. 
            Chỉ trả lời câu hỏi bằng thông tin được cung cấp, nếu không được cung cấp thông tin, hãy xin lỗi và nhờ hỏi 
            câu khác."""
        },
        {
            "role": "user",
            "content": user_query
        }
    ]

# Tạo chuỗi mô tả cơ sở dữ liệu
def create_database_schema_string():
    conn = get_database_connection()
    try:
        table_dicts = get_database_info(conn)
        database_schema_string = "\n".join(
            [
                f"Table: {table['table_name']}\nColumns: {', '.join(table['column_names'])}"
                for table in table_dicts
            ]
        )
    finally:
        conn.close()
    return database_schema_string

# Lấy thông tin cơ sở dữ liệu
def get_database_info(conn):
    table_dicts = []
    for table_name in get_table_names(conn):
        column_names = get_column_names(conn, table_name)
        table_dicts.append({"table_name": table_name, "column_names": column_names})
    return table_dicts

# Lấy danh sách tên bảng
def get_table_names(conn):
    table_names = []
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            AND table_type='BASE TABLE';
        """)
        table_names = [table[0] for table in cursor.fetchall()]
    return table_names

# Lấy danh sách tên cột của bảng
def get_column_names(conn, table_name):
    column_names = []
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='{table_name}'
            AND table_schema='public';
        """)
        column_names = [col[0] for col in cursor.fetchall()]
    return column_names

@app.route('/ask', methods=['POST'])
def ask():
    data = request.get_json()
    user_query = data.get('question')
    
    if not user_query:
        return jsonify({"error": "Question is required"}), 400

    # Tạo tin nhắn cho OpenAI
    messages = create_openai_messages(user_query)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "ask_database",
                "description": "Use this function to answer user questions about our database. Input should be a fully formed SQL query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": f"""
                                    SQL query extracting info to answer the user's question.
                                    SQL should be written using this database schema:
                                    {create_database_schema_string()}
                                    The query should be returned in plain text, not in JSON.
                                    """,
                        }
                    },
                    "required": ["query"],
                },
            }
        }
    ]
    
    try:
        # Gửi yêu cầu đến OpenAI
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message
        
        # Kiểm tra tool_calls
        tool_calls = getattr(response_message, 'tool_calls', [])
        if tool_calls:
            tool_call_id = tool_calls[0].id
            tool_function_name = tool_calls[0].function.name
            tool_query_string = json.loads(tool_calls[0].function.arguments)['query']

            # Truy vấn cơ sở dữ liệu
            conn = get_database_connection()
            try:
                results = ask_database(conn, tool_query_string)
                # Tạo tin nhắn phản hồi từ công cụ
                tool_message = {
                    "role": "tool", 
                    "tool_call_id": tool_call_id, 
                    "name": tool_function_name, 
                    "content": results
                }

                # Gửi phản hồi từ công cụ đến OpenAI
                model_response_with_function_call = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages + [response_message.to_dict(), tool_message]  # Chuyển đổi response_message thành từ điển
                )
                final_response = model_response_with_function_call.choices[0].message.content
            finally:
                conn.close()
        else:
            final_response = response_message.content
    
        return jsonify({"response": final_response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
