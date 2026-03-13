import datetime, os, requests
from flask import Flask, render_template, redirect, url_for, request
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, EmailField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, Email
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, String, DateTime, Text, Date, ForeignKey, or_, and_, Boolean
from sqlalchemy.orm import mapped_column, DeclarativeBase, Mapped, relationship
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv, find_dotenv
from flask_socketio import SocketIO, emit, join_room


class Base(DeclarativeBase):
    pass

load_dotenv(find_dotenv())

app = Flask(__name__)
uri = os.environ.get("DB_URI", "sqlite:///chat-db.sqlite")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.secret_key = os.getenv("SECRET_KEY")
db = SQLAlchemy(model_class=Base)
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
socketio = SocketIO(app)

#db user model
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password: Mapped[str] = mapped_column(String, nullable=False)
    chats_as_user1 = relationship("Chat", foreign_keys="[Chat.user1Id]", back_populates="user1")
    chats_as_user2 = relationship("Chat", foreign_keys="[Chat.user2Id]", back_populates="user2")
    messages = relationship("Message", back_populates="sender")

#db chat model
class Chat(db.Model):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user1Id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    user2Id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    createdAt: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    user1 = relationship("User", foreign_keys=[user1Id], back_populates="chats_as_user1")
    user2 = relationship("User", foreign_keys=[user2Id], back_populates="chats_as_user2")
    messages = relationship("Message", back_populates="chat",  order_by="Message.timestamp", cascade="all, delete")

#db message model
class Message(db.Model):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chatId: Mapped[int] = mapped_column(Integer, ForeignKey("chats.id"), nullable=False)
    senderId: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    isRead: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    chat = relationship("Chat", foreign_keys=[chatId], back_populates="messages")
    sender = relationship("User", foreign_keys=[senderId], back_populates="messages")

#Falsk forms
class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=20)])
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=32)])
    password2 = PasswordField("Repeat Password", validators=[DataRequired(), EqualTo("password")])

class SearchForm(FlaskForm):
    name = StringField("username", validators=[DataRequired()])
    submit = SubmitField("Search")

class SendMessageForm(FlaskForm):
    message = StringField("Message", validators=[DataRequired()])

class EditMessageForm(FlaskForm):
    message = StringField("Message", validators=[DataRequired()])
    submit =  SubmitField("Save Changes")

class ForgotPasswordForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=32)])
    repeat_password = PasswordField("Repeat Password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Reset Password")
#creating db if it is not created yet if it is created then it just passes
try:
    with app.app_context():
        db.create_all()
except Exception as e:
    pass


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    searchform = SearchForm()
    sendMessageForm = SendMessageForm()
    editMessageForm = EditMessageForm()

    chats_as_user1 = current_user.chats_as_user1
    chats_as_user2 = current_user.chats_as_user2
    all_chats = chats_as_user1 + chats_as_user2
    active_chat = None

    all_chats.sort(key=lambda c: c.messages[-1].timestamp if c.messages else c.createdAt, reverse=True)

    #chat open function
    if request.args.get("active_chat"):
        active_chat = db.session.execute(
            db.select(Chat).where(Chat.id == int(request.args.get("active_chat")))
        ).scalar()
        if active_chat:
            if current_user.id == active_chat.user1Id or current_user.id == active_chat.user2Id:
                msgs = [msg for msg in active_chat.messages if msg.senderId != current_user.id and msg.isRead == False]
                for msg in msgs:
                    msg.isRead = True
                db.session.commit()
            else:
                return redirect("/")
        else:
            return redirect("/")

    #search method
    if searchform.validate_on_submit():
        data = db.session.execute(db.select(User)).scalars().all()
        data = [user for user in data if ("").join(searchform.name.data.split(" ")).lower() in ("").join(str(user.username).split(" ")).lower() and current_user.username != user.username]
        return render_template("index.html", searchform=searchform, search_results=data, chats_as_user1=chats_as_user1, chats_as_user2=chats_as_user2, all_chats=all_chats,  active_chat=active_chat, sendMessageForm=sendMessageForm, editMessageForm=editMessageForm)

    return render_template("index.html", searchform=searchform, chats_as_user1=chats_as_user1, chats_as_user2=chats_as_user2, all_chats=all_chats, active_chat=active_chat, sendMessageForm=sendMessageForm, editMessageForm=editMessageForm)

#sending message using socketio
@socketio.on('send_message')
def handle_message(data):
    chat_id = data["chat_id"]
    content = data["content"]
    chat = db.session.execute(db.select(Chat).where(Chat.id == int(chat_id))).scalar()
    new_message = Message(content=content, chat=chat, sender=current_user)
    db.session.add(new_message)
    db.session.commit()
    messages_html = render_template('messagesPartial.html',
                                    messages=chat.messages,
                                    current_user=current_user,
                                    chat_id=chat_id)
    emit('refresh_messages', {'html': messages_html,
                              'preview': content,
                              'chat_id': chat_id,
                              'sender_id': current_user.id,
                              'time': new_message.timestamp.strftime('%H:%M')
                              }, room=str(chat_id))

#editing message using socketio
@socketio.on("edit_message")
def handle_edit(data):
    chat_id = data["chat_id"]
    message_id = data["msg_id"]
    content = data["content"]

    message_to_edit = db.session.execute(db.select(Message).where(Message.id == int(message_id))).scalar()
    if message_to_edit and message_to_edit.senderId == current_user.id:
        message_to_edit.content = content
        db.session.commit()
        messages_html = render_template('messagesPartial.html',
                                        messages=message_to_edit.chat.messages,
                                        current_user=current_user,
                                        chat_id=chat_id)
        emit('refresh_messages', {'html': messages_html,
                                  'preview': content,
                                  'chat_id': chat_id,
                                  'sender_id': current_user.id,
                                  'time': message_to_edit.timestamp.strftime('%H:%M')
                                  }, room=str(chat_id))

#deleting message using socketio
@socketio.on('delete_message')
def handle_delete(data):
    chat_id = data["chat_id"]
    message_id = data["msg_id"]
    chat = db.session.execute(db.select(Chat).where(Chat.id == int(chat_id))).scalar()

    if message_id:
        message = db.session.execute(db.select(Message).where(Message.id == int(message_id))).scalar()
        db.session.delete(message)
        db.session.commit()
        messages = db.session.execute(db.select(Message).where(Message.chatId == int(chat_id))).scalars().all()
        messages_html = render_template('messagesPartial.html',
                                        messages=chat.messages,
                                        current_user=current_user,
                                        chat_id=chat_id)
        emit('refresh_messages', {'html': messages_html,
                                  'preview': messages[-1].content,
                                  'chat_id': chat_id,
                                  'sender_id': messages[-1].senderId,
                                  'time': message.timestamp.strftime('%H:%M')
                                  }, room=str(chat_id))

@socketio.on('join')
def on_join(data):
    join_room(str(data['chat_id']))

#old method of deleting using flask not using anymore
@app.route('/delete', methods=['GET', 'POST'])
def delete():
    chat_id = request.args.get('chat_id')
    message_id = request.args.get('message_id')
    try:
        message_to_delete = db.session.execute(db.select(Message).where(Message.id == int(message_id))).scalar()
        db.session.delete(message_to_delete)
        db.session.commit()
    except Exception as e:
        print(e)

    return redirect(url_for('index', active_chat=chat_id))

#old method of editing using flask not using anymore
@app.route("/edit_message", methods=['GET', 'POST'])
@login_required
def edit_message():
    msg_id = request.args.get("msg_id")
    content = request.form.get("message")
    chat_id = request.args.get('chat_id')

    if msg_id:
        try:
            message = db.session.execute(db.select(Message).where(Message.id == int(msg_id))).scalar()
            message.content = content
            db.session.commit()
        except Exception as e:
            print(e)

    return redirect(url_for('index', active_chat=chat_id))

#creating chat function using flask
@app.route('/add_new_chat', methods=['GET', 'POST'])
@login_required
def new_chat():
    sendto_id = request.args.get('sendto_id')

    if sendto_id:
        user = db.session.execute(db.select(User).where(User.id == int(sendto_id))).scalar()

        chats = db.session.execute(db.select(Chat).where(and_(or_(Chat.user1Id == current_user.id, Chat.user2Id == current_user.id), or_(Chat.user2Id == user.id, Chat.user1Id == user.id)))).scalars().all()

        if not chats:
            new_chat = Chat(user1=current_user, user2=user)
            db.session.add(new_chat)
            db.session.commit()
            return redirect(url_for('index', active_chat=new_chat.id))
        else:
            return redirect(url_for('index', active_chat=chats[0].id))

    return redirect(url_for('index'))

#login method
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    error = None

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if form.validate_on_submit():
        user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
        if user :
            if check_password_hash(user.password, form.password.data):
                login_user(user)
                return redirect("/")
            else:
                error = "Wrong Password!"
        else:
            error = "User with that email does not exist."


    return render_template('login.html', form=form, error=error)

#forgot password method
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    error = None

    if form.validate_on_submit():
        user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
        if user:
            try:
                hashed_password = generate_password_hash(password=form.password.data, method="pbkdf2:sha256", salt_length=8)
                user.password = hashed_password
                db.session.commit()
            except Exception as e:
                error = "Unexpected Error, Please try again later."
            else:
                return redirect(url_for('login'))
        else:
            error = "User with that email does not exist."

    return render_template('forgotPassword.html', form=form, error=error)

#register method
@app.route("/register", methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    error = None

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        if form.validate_on_submit():
            hashed_password = generate_password_hash(form.password.data, method="pbkdf2:sha256", salt_length=8)
            try:
                new_user = User(username=form.username.data, email=form.email.data, password=hashed_password)
                db.session.add(new_user)
                db.session.commit()
            except IntegrityError as err:
                error = "Account with that email already exists."
            except Exception as e:
                error = "Error, Please Try Again Later."
            else:
                return redirect(url_for('login'))


        elif form.password.data and form.password2.data and form.password.data != form.password2.data:
           error = "Repeat Password Field must be equal to password."
        else:
            error = "Invalid Credentials, Please Try Again."

    return render_template('register.html', form=form, error=error)

#logout function with route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect("/login")

if __name__ == '__main__':
    socketio.run(app, debug=True)