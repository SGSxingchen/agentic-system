# 场景测试：Flask 用户管理 API 开发

> 测试时间：2026-03-25 12:39 ~ 13:00 (Asia/Shanghai)
> 测试环境：WSL2 Ubuntu, Python 3.x, FastAPI 后端 (uvicorn port 8002)
> LLM 配置：provider=openai, model=claude-sonnet-4-20250514, base_url=http://156.238.228.118:8317/v1

---

## 1. 任务规划 (Planner Agent)

**请求:**
```json
POST http://localhost:8002/api/agents/planner/invoke
{
  "data": {
    "requirement": "我需要用 Flask + SQLAlchemy 开发一个用户管理 RESTful API。功能包括：用户注册（密码用 bcrypt 哈希）、JWT 登录、获取/修改/删除用户信息。请帮我分解任务。"
  }
}
```

**响应 (status=ok):**

返回了 12 个子任务的结构化计划：

| # | 任务名 | 描述 | 分配Agent | 依赖 | 优先级 |
|---|--------|------|-----------|------|--------|
| 1 | setup_project_structure | 创建项目目录结构，初始化Flask应用，配置基本的项目文件和依赖 | coder | 无 | 1 |
| 2 | design_database_models | 设计并实现User数据模型，使用SQLAlchemy定义表结构，包含用户字段和密码哈希存储 | coder | setup_project_structure | 2 |
| 3 | implement_password_hashing | 实现bcrypt密码哈希功能，包括密码加密和验证方法 | coder | design_database_models | 3 |
| 4 | implement_jwt_auth | 实现JWT认证系统，包括token生成、验证和中间件装饰器 | coder | implement_password_hashing | 4 |
| 5 | implement_user_registration | 实现用户注册API端点，包括输入验证、密码哈希和用户创建 | coder | implement_password_hashing | 5 |
| 6 | implement_user_login | 实现用户登录API端点，验证凭据并返回JWT token | coder | implement_jwt_auth, implement_user_registration | 6 |
| 7 | implement_user_info_apis | 实现获取、修改、删除用户信息的API端点，包含JWT认证保护 | coder | implement_user_login | 7 |
| 8 | add_error_handling | 添加全局错误处理、输入验证和API响应格式标准化 | coder | implement_user_info_apis | 8 |
| 9 | review_code_quality | 审查代码质量、安全性、RESTful设计规范和最佳实践 | reviewer | add_error_handling | 9 |
| 10 | write_unit_tests | 编写用户注册、登录、CRUD操作的单元测试和集成测试 | tester | add_error_handling | 10 |
| 11 | write_api_tests | 编写API端点测试，包括认证流程、权限验证和错误场景测试 | tester | write_unit_tests | 11 |
| 12 | final_review | 最终代码和测试审查，确保所有功能正常运行并符合要求 | reviewer | review_code_quality, write_api_tests | 12 |

**评估:** ✅ 通过
- LLM 返回了有意义且详细的规划
- 子任务分解合理，从项目初始化到最终审查覆盖完整开发流程
- 依赖关系正确，体现了合理的开发顺序
- 任务粒度适中，既不过粗也不过细
- 正确区分了 coder、reviewer、tester 三种 agent 的职责
- 输出格式为严格的 JSON，符合系统预期

---

## 2. 代码生成 - 数据模型 (Coder Agent)

**请求:**
```json
POST http://localhost:8002/api/agents/coder/invoke
{
  "data": {
    "task": "请用 Flask + SQLAlchemy 实现 User 数据模型，字段包含 id、username、email、password_hash、created_at。包含密码哈希和验证方法。使用 bcrypt 进行密码加密。"
  }
}
```

**响应 (status=ok):**

```python
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from typing import Optional

db = SQLAlchemy()

class User(db.Model):
    """用户数据模型
    
    包含用户基本信息和密码管理功能
    """
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __init__(self, username: str, email: str, password: str):
        self.username = username
        self.email = email
        self.set_password(password)
    
    def set_password(self, password: str) -> None:
        if not password or len(password.strip()) == 0:
            raise ValueError("密码不能为空")
        self.password_hash = generate_password_hash(
            password, 
            method='pbkdf2:sha256',
            salt_length=16
        )
    
    def check_password(self, password: str) -> bool:
        if not password:
            return False
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self, include_sensitive: bool = False) -> dict:
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_sensitive:
            data['password_hash'] = self.password_hash
        return data
    
    @classmethod
    def find_by_username(cls, username: str) -> Optional['User']:
        return cls.query.filter_by(username=username).first()
    
    @classmethod
    def find_by_email(cls, email: str) -> Optional['User']:
        return cls.query.filter_by(email=email).first()
    
    def __repr__(self) -> str:
        return f'<User {self.username}>'
```

- **建议文件路径:** `models/user.py`
- **语言:** Python
- **描述:** 基于Flask-SQLAlchemy的用户数据模型，包含完整的用户信息字段和密码管理功能。使用Werkzeug的密码哈希功能（基于PBKDF2-SHA256算法）进行安全的密码加密。

**评估:** ✅ 通过
- 代码结构清晰，包含所有要求的字段 (id, username, email, password_hash, created_at)
- 密码哈希使用 werkzeug 的 `generate_password_hash` (PBKDF2-SHA256)，注意：需求说用 bcrypt，但 LLM 选择了 PBKDF2（也是安全的替代方案，但不完全符合需求）
- 包含 `set_password`、`check_password`、`to_dict`、`find_by_username`、`find_by_email` 等实用方法
- 有完善的类型注解和文档字符串
- `to_dict` 方法支持控制是否暴露敏感信息，设计合理
- 输出格式为标准 JSON（code, language, file_path, description），符合 Coder Agent 规范

---

## 3. 代码生成 - API 路由 (Coder Agent)

**请求:**
```json
POST http://localhost:8002/api/agents/coder/invoke
{
  "data": {
    "task": "基于以下 User 模型，实现 Flask RESTful API 路由：POST /register（用户注册）, POST /login（返回JWT token）, GET /users/<id>（获取用户信息）, PUT /users/<id>（修改用户信息）, DELETE /users/<id>（删除用户）。包含完善的错误处理和JWT认证装饰器。\n\nUser模型已经实现，包含以下方法：\n- set_password(password): 设置密码（bcrypt哈希）\n- check_password(password): 验证密码\n- to_dict(): 转为字典\n- find_by_username(username): 按用户名查找\n- find_by_email(email): 按邮箱查找\n\n请使用 flask, flask-jwt-extended 实现完整的路由代码。"
  }
}
```

**响应 (status=ok):**

```python
from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.exceptions import BadRequest
from functools import wraps
import re
from datetime import timedelta

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

jwt = JWTManager(app)

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    if len(password) < 6:
        return False, "密码长度至少6位"
    if not re.search(r'[A-Za-z]', password):
        return False, "密码必须包含字母"
    if not re.search(r'\d', password):
        return False, "密码必须包含数字"
    return True, ""

def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except BadRequest as e:
            return jsonify({'error': str(e.description)}), 400
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            app.logger.error(f'Unexpected error: {str(e)}')
            return jsonify({'error': '服务器内部错误'}), 500
    return decorated_function

def owner_or_admin_required(f):
    @wraps(f)
    @jwt_required()
    def decorated_function(user_id, *args, **kwargs):
        current_user_id = get_jwt_identity()
        if str(current_user_id) != str(user_id):
            return jsonify({'error': '权限不足'}), 403
        return f(user_id, *args, **kwargs)
    return decorated_function

@app.route('/register', methods=['POST'])
@handle_errors
def register():
    data = request.get_json()
    if not data:
        raise BadRequest('请提供JSON数据')
    required_fields = ['username', 'email', 'password']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        raise BadRequest(f'缺少必填字段: {", ".join(missing_fields)}')
    username = data['username'].strip()
    email = data['email'].strip().lower()
    password = data['password']
    if len(username) < 3 or len(username) > 20:
        raise BadRequest('用户名长度必须在3-20个字符之间')
    if not validate_email(email):
        raise BadRequest('邮箱格式不正确')
    is_valid, error_msg = validate_password(password)
    if not is_valid:
        raise BadRequest(error_msg)
    if User.find_by_username(username):
        raise BadRequest('用户名已存在')
    if User.find_by_email(email):
        raise BadRequest('邮箱已被注册')
    user = User(username=username, email=email, full_name=data.get('full_name', '').strip())
    user.set_password(password)
    return jsonify({'message': '注册成功', 'user': user.to_dict()}), 201

@app.route('/login', methods=['POST'])
@handle_errors
def login():
    data = request.get_json()
    if not data:
        raise BadRequest('请提供JSON数据')
    username_or_email = data.get('username_or_email', '').strip()
    password = data.get('password', '')
    if not username_or_email or not password:
        raise BadRequest('请提供用户名/邮箱和密码')
    if '@' in username_or_email:
        user = User.find_by_email(username_or_email.lower())
    else:
        user = User.find_by_username(username_or_email)
    if not user or not user.check_password(password):
        raise BadRequest('用户名/邮箱或密码错误')
    access_token = create_access_token(identity=user.id)
    return jsonify({'message': '登录成功', 'access_token': access_token, 'user': user.to_dict()}), 200

@app.route('/users/<int:user_id>', methods=['GET'])
@owner_or_admin_required
@handle_errors
def get_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': user.to_dict()}), 200

@app.route('/users/<int:user_id>', methods=['PUT'])
@owner_or_admin_required
@handle_errors
def update_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    data = request.get_json()
    if not data:
        raise BadRequest('请提供JSON数据')
    updatable_fields = ['full_name', 'email']
    updated = False
    for field in updatable_fields:
        if field in data:
            value = data[field].strip() if isinstance(data[field], str) else data[field]
            if field == 'email':
                if not validate_email(value):
                    raise BadRequest('邮箱格式不正确')
                existing_user = User.find_by_email(value.lower())
                if existing_user and existing_user.id != user.id:
                    raise BadRequest('邮箱已被其他用户注册')
                value = value.lower()
            if getattr(user, field) != value:
                setattr(user, field, value)
                updated = True
    if 'password' in data:
        new_password = data['password']
        is_valid, error_msg = validate_password(new_password)
        if not is_valid:
            raise BadRequest(error_msg)
        user.set_password(new_password)
        updated = True
    if not updated:
        return jsonify({'message': '没有数据需要更新'}), 200
    return jsonify({'message': '用户信息更新成功', 'user': user.to_dict()}), 200

@app.route('/users/<int:user_id>', methods=['DELETE'])
@owner_or_admin_required
@handle_errors
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'message': '用户删除成功'}), 200

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Token已过期，请重新登录'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(error):
    return jsonify({'error': 'Token无效'}), 401

@jwt.unauthorized_loader
def missing_token_callback(error):
    return jsonify({'error': '请提供有效的访问token'}), 401
```

- **建议文件路径:** `app/routes/auth.py`
- **语言:** Python
- **描述:** 完整的Flask RESTful API路由实现，包含用户注册、登录、获取用户信息、修改和删除用户功能。使用JWT进行身份认证，包含完善的数据验证、错误处理和权限控制。

**评估:** ⚠️ 部分通过
- 实现了所有 5 个 API 端点（register, login, get_user, update_user, delete_user）
- JWT 认证和权限装饰器设计合理（owner_or_admin_required）
- 输入验证全面（邮箱格式、密码强度、必填字段）
- 错误处理装饰器设计简洁
- **问题：**
  - User 构造函数传入了不存在的 `full_name` 参数
  - 缺少 `db.session.add()` 和 `db.session.commit()` 数据库操作
  - delete 路由没有实际删除操作
  - JWT 密钥硬编码
  - 缺少数据库初始化配置

---

## 4. 代码审查 (Reviewer Agent)

**请求:**
```json
POST http://localhost:8002/api/agents/reviewer/invoke
{
  "data": {
    "code": "[上述两段完整代码合并]",
    "language": "python",
    "file_path": "flask_user_api",
    "task": "Flask用户管理RESTful API，包含注册、登录、CRUD操作"
  }
}
```

**响应 (status=ok):**

### 审查结论: ❌ 未通过 (approved=false, severity=9/10)

### 发现的问题：

| # | 类型 | 严重度 | 描述 | 位置提示 |
|---|------|--------|------|----------|
| 1 | bug | critical | 注册接口尝试使用不存在的 full_name 字段创建用户，但 User 模型中没有该字段定义 | `register()` 函数中 `User(... full_name=...)` |
| 2 | bug | critical | 数据库操作缺少 `db.session.add()` 和 `db.session.commit()`，导致数据无法保存到数据库 | register() 和 update_user() |
| 3 | bug | critical | 删除用户接口只返回成功消息但实际没有删除数据库记录 | `delete_user()` 缺少 `db.session.delete(user)` |
| 4 | bug | critical | 更新用户接口中尝试更新不存在的 full_name 字段 | `updatable_fields = ['full_name', 'email']` |
| 5 | security | critical | JWT 密钥使用硬编码的默认值，存在安全风险 | `'your-secret-key-change-this-in-production'` |
| 6 | logic | major | 缺少数据库初始化和配置，Flask 应用无法正常运行 | 缺少 `db.init_app(app)` |
| 7 | performance | major | 数据库操作没有异常处理和回滚机制 | 所有数据库操作缺少 try-except 和 rollback |
| 8 | security | minor | 密码长度要求过低，只要求6位且规则不够严格 | `validate_password()` |

### 改进建议：
1. 在 User 模型中添加 full_name 字段或从代码中移除对该字段的引用
2. 为所有数据库操作添加 `db.session.add()`、`db.session.commit()` 和异常处理
3. 将 JWT 密钥配置为环境变量，不要硬编码
4. 添加数据库配置和初始化代码
5. 实现数据库事务的回滚机制
6. 增强密码强度要求（如最少8位、包含特殊字符等）
7. 添加请求频率限制防止暴力破解
8. 添加日志记录用于审计和调试

### 审查总结：
> 代码存在多个严重问题，包括数据库操作逻辑错误、字段不匹配、安全配置问题等，必须修复后才能投入使用。

**评估:** ✅ 通过
- Reviewer 准确识别了所有关键问题（尤其是 full_name 字段不匹配、缺少数据库操作）
- 问题分类准确（bug/security/logic/performance）
- 严重度评估合理（9/10）
- 建议具体可操作
- 输出格式为标准 JSON，字段完整（approved, issues, suggestions, severity, summary）

---

## 总结

### 整体测试结果: ✅ 通过

| 步骤 | Agent | 状态 | 耗时 | 备注 |
|------|-------|------|------|------|
| 1. 任务规划 | Planner | ✅ 成功 | ~15s | 12个子任务，结构化JSON |
| 2. 代码生成-模型 | Coder | ✅ 成功 | ~10s | 完整User模型 |
| 3. 代码生成-路由 | Coder | ✅ 成功 | ~15s | 5个API端点 |
| 4. 代码审查 | Reviewer | ✅ 成功 | ~12s | 发现8个问题，severity=9 |

### 整体体验评价

**优点：**
1. **系统稳定性好** — 4次 API 调用全部成功，无 500 错误
2. **LLM 响应质量高** — 所有 Agent 都返回了有意义、专业的内容
3. **结构化输出可靠** — JSON 解析成功率 100%，未出现格式错误
4. **Agent 职责划分清晰** — Planner 规划、Coder 编码、Reviewer 审查，各司其职
5. **Reviewer 审查深入** — 准确发现了 Coder 代码中的真实 bug（如 full_name 字段不匹配、缺少 db 操作）
6. **端到端流程通畅** — 从需求到代码到审查的完整工作流正常运行

**发现的问题：**
1. **Coder 无上下文记忆** — 第二次调用 Coder 时，它不记得第一次生成的模型代码，导致引用了不存在的 `full_name` 字段。需要在请求中手动传递上下文。
2. **密码哈希方案不完全符合需求** — 需求要求 bcrypt，Coder 使用了 PBKDF2-SHA256（werkzeug 默认），虽然也安全但不是指定方案。
3. **Coder 生成的代码缺少关键数据库操作** — 注册、更新、删除都没有实际的 session 操作，代码不能直接运行。
4. **API 请求格式文档不够直观** — 需要查看源码才能确定 `data.requirement` vs `data.task` 的区别，建议在 API 文档中更明确说明。
5. **Agent 之间没有自动串联** — 需要手动将 Coder 的输出传递给 Reviewer，系统没有自动 workflow 编排（虽然代码中有 WorkflowOrchestrator，但手动 invoke 时不走 workflow）。

### 建议改进：
1. 为 Coder Agent 添加对话历史/上下文传递机制
2. 实现自动化 workflow：Planner → Coder → Reviewer 自动串联
3. Coder 的 system prompt 应强调生成可直接运行的完整代码
4. API 文档中明确标注各 Agent 期望的 data 字段格式
