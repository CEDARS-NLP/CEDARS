"""
Loading Libraries
"""
import sys
import pymongo
import pandas as pd
from datetime import datetime



class DatabaseConnector:
   def __init__(self, db_name, col_name):
      myclient = pymongo.MongoClient("mongodb://localhost:27017/")

      self.database_connector = myclient[db_name] # create / open database

      self.col_name = col_name


   def insert_single(self, data):
      collection = self.database_connector[self.col_name]
      collection.insert_one(data)
     

   def insert_multi(self, data):
      collection = self.database_connector[self.col_name]
      collection.insert_many(data)
     

   def create_collection(self, data):
      try:
         assert self.col_name not in self.database_connector.list_collection_names()
      except:
         raise Exception(f'A collection named {self.col_name} already exists in this database. Try changing a different collection name or inserting the data to this collection with the insert_single or insert_multi commands.')

   

      if type(data) == type({}):
         self.insert_single(data,)
      else:
         self.insert_multi(data)

   def read_all(self):
      return [i for i in self.database_connector[self.col_name].find()]
   
   def read_one(self):
      return self.database_connector[self.col_name].find_one()

   def read_patient(self, patient_id):
      data_generator = self.database_connector[self.col_name].find({"patient_id" : int(patient_id)})
      return [i for i in data_generator]

   def read_patients(self, patient_ids):
      data = []
      for patient_id in patient_ids:
         data.extend(self.read_patient(patient_id))
      return data


   def read_text_id(self, id):
      data_generator = self.database_connector[self.col_name].find({"text_id" : id})
      return [i for i in data_generator]

   def read_text_ids(self, text_ids):
      data = []
      for text_id in text_ids:
         data.extend(self.read_text_id(text_id))
      return data

   def read_regex(self, regex_smt, field_name):
      query = { field_name : { "$regex": regex_smt } }

      data_generator = self.database_connector[self.col_name].find(query)

      return [i for i in data_generator]

   def delete_text(self, text_id):
      return self.database_connector[self.col_name].delete_one({"text_id" : text_id})

   def delete_patient(self, patient_id):
      return self.database_connector[self.col_name].delete_many({"patient_id" : patient_id})

   def clear_collection(self):
      return self.database_connector[self.col_name].delete_many({})

   def drop_collection(self):
      return self.database_connector[self.col_name].drop()


   def update_text(self, text_id, new_data):
      return self.database_connector[self.col_name].update_one({"text_id" : text_id}, {"$set" : new_data})

   def update_date(self, text_id, new_date):
      return self.database_connector[self.col_name].update_one({"text_id" : text_id}, { "$set": { "text_date": new_date } })
   

   def create_project(self, project_name, investigator_name, cedars_version):
      self.create_info_col(project_name, investigator_name, cedars_version)

      self.populate_annotations()
      self.populate_notes()
      self.populate_users()
      self.populate_dictionaries()
      self.populate_query()

      print("Database creation successful!")
   
   def create_info_col(self, project_name, investigator_name, cedars_version):
      collection = self.database_connector["INFO"]
      info = {"creation_time" : datetime.now(), "project" : project_name,
              "investigator" : investigator_name, "CEDARS_version" : cedars_version}
     
      collection.insert_one(info)


   def populate_annotations(self):
      annotations = self.database_connector["ANNOTATIONS"]

      index_columns = ["text_id", "paragraph_id", "sentence_id", "token_id"]

      annotations.create_index("patient_id", unique = False)
      annotations.create_index("CUI", unique = False)
      annotations.create_index("lemma", unique = False)
      annotations.create_index("doc_id", unique = False)

      annotations.create_index(index_columns, unique = True, name = "annotations_index")

      patients = self.database_connector["PATIENTS"]
      # To force mongodb to create an empty collection with only the default index, we create and drop a dummy ID
      patients.create_index("id", unique = True)
      patients.drop_index("id_1")

   def populate_notes(self):
      notes = self.database_connector["NOTES"]

      notes.create_index("patient_id", unique = False)
      notes.create_index("doc_id", unique = False)
      notes.create_index("text_id", unique = True)

   def populate_users(self):
      users = self.database_connector["USERS"]

      users.create_index("user", unique = True)

   def populate_dictionaries(self):
      mrconso = self.database_connector["UMLS_MRCONSO"]
      mrconso.create_index("CUI", unique = False)
      mrconso.create_index("STR", unique = False)
      mrconso.create_index("grams", unique = False)


      mrrel = self.database_connector["UMLS_MRREL"]
      mrrel.create_index("CUI", unique = False)

   def populate_query(self):
      query_col = self.database_connector["QUERY"]
      # To force mongodb to create an empty collection with only the default index, we create and drop a dummy ID
      query_col.create_index("id", unique = True)
      query_col.drop_index("id_1")

if __name__ == "__main__":
    csv_name = "simulated_patients.csv"
    db_name = "PYCEDARS"

    col_name = "simulated_patients"

    raw_data = pd.read_csv(csv_name)

    list_data = list(raw_data.T.to_dict().values())

    conn = DatabaseConnector(db_name, col_name)


    conn.drop_collection()

    conn.create_project("Pycedars test", "Kayan", 0.1)