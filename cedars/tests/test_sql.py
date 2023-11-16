import sqlalchemy
import sqlite3
import os

from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import DeclarativeBase

from sqlalchemy import inspect


class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "Users"
    id = Column(Integer, primary_key=True, autoincrement = True) 
    name = Column(String)
    fullname = Column(String)
    
    def __repr__(self) -> str:
        '''
        Format used to print the table output to console.
        '''
        return f"User(id={self.id!r}, name={self.name!r}, fullname={self.fullname!r})"
    
    def get_column_names(self = None):
        return ["id", "name", "fullname"]
    
class User2(Base):
    __tablename__ = "Users2"
    id2 = Column(Integer, ForeignKey(User.id)) 
    name = Column(String, primary_key = True)
    fullname = Column(String)

db_name = "test_db"
# If a database with the given name does not exist, we create a database file in the app directory
if f'{db_name}.db' not in os.listdir():
    sqlite3.connect(f'{db_name}.db')

db_engine = sqlalchemy.create_engine(f'sqlite:///{db_name}.db')
insp = inspect(db_engine)

exist = sqlalchemy.inspect(db_engine).has_table("users")

Base.metadata.create_all(db_engine)

Session = sessionmaker(bind=db_engine) 
session = Session() 
  
# add a new user to the database 
user = User(name='john', fullname='John Doe') 
# session.add(user) 
session.commit() 
  
session.query(User).filter(User.id == 31).update({User.name : "asdfkalfjdak"})
session.commit()

users = session.query(User).filter(User.name == 'a').all()

print(users)