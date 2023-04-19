from datetime import datetime, timedelta
from airflow import DAG, Dataset
from airflow.operators.bash_operator import BashOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator  # Tâches de création de table
#4 Codes suivants pour : Tâche de récupération de données
import os
import requests
from airflow.decorators import task
from airflow.providers.postgres.hooks.postgres import PostgresHook


default_args = {
    'owner': 'airflow',
    'depends_on_past': False    
}

my_dataset = Dataset('/tmp/data.csv')

# Define the consumer DAG
with DAG(dag_id='producer_aware', 
        start_date = datetime.now(),
        schedule_interval = timedelta(minutes=5),
        default_args=default_args) as dag:

    generate_dataset = BashOperator(
        task_id='generate_dataset',
        outlets=[my_dataset],
        bash_command='echo "data1,data2,data3\n" >> /tmp/data.csv',
    )

    check_file_task = BashOperator(
        task_id='check_file',
        bash_command='cat /tmp/data.csv',
    )

    generate_dataset >> check_file_task

# Define the consumer DAG
with DAG(dag_id='consumer_aware', 
        schedule = [my_dataset],
        start_date = datetime.now(),
        default_args=default_args) as dag:

    # Define the task that consumes the dataset
    consume_dataset = BashOperator(
        task_id="consume_dataset",
        bash_command="cat /tmp/data.csv",
        retries=3,
    )


# Tâches de création de table
"""
Il est possible d'utiliser PostgresOperator afin de définir des tâches qui 
créeront des tables dans la base de données postgres.

Il est prévu de créer deux tables : une pour faciliter le nettoyage des 
données (employees_temp) et une autre pour stocker les données nettoyées 
(employees).
"""

create_employees_table = PostgresOperator(
    task_id="create_employees_table",
    postgres_conn_id="tutorial_pg_conn",
    sql="""
        CREATE TABLE IF NOT EXISTS employees (
            "Serial Number" NUMERIC PRIMARY KEY,
            "Company Name" TEXT,
            "Employee Markme" TEXT,
            "Description" TEXT,
            "Leave" INTEGER
        );""",
)

create_employees_temp_table = PostgresOperator(
    task_id="create_employees_temp_table",
    postgres_conn_id="tutorial_pg_conn",
    sql="""
        DROP TABLE IF EXISTS employees_temp;
        CREATE TABLE employees_temp (
            "Serial Number" NUMERIC PRIMARY KEY,
            "Company Name" TEXT,
            "Employee Markme" TEXT,
            "Description" TEXT,
            "Leave" INTEGER
        );""",
)


#Tâche de récupération de données
"""Ici, les données sont récupérées, enregistrées dans un fichier sur 
l'instance Airflow, puis chargées à partir de ce fichier dans une table 
intermédiaire afin de pouvoir exécuter les étapes de nettoyage des données."""
@task
def get_data():
    # REMARQUE : configurez cela selon les besoins de votre environnement Airflow.
    data_path = "/opt/airflow/dags/files/employees.csv"
    os.makedirs(os.path.dirname(data_path), exist_ok=True)

    url = "https://raw.githubusercontent.com/apache/airflow/main/docs/apache-airflow/tutorial/pipeline_example.csv"

    response = requests.request("GET", url)

    with open(data_path, "w") as file:
        file.write(response.text)

    postgres_hook = PostgresHook(postgres_conn_id="tutorial_pg_conn")
    conn = postgres_hook.get_conn()
    cur = conn.cursor()
    with open(data_path, "r") as file:
        cur.copy_expert(
            "COPY employees_temp FROM STDIN WITH CSV HEADER DELIMITER AS ',' QUOTE '\"'",
            file,
        )
    conn.commit()



@task
def merge_data():
    query = """
        INSERT INTO employees
        SELECT *
        FROM (
            SELECT DISTINCT *
            FROM employees_temp
        ) t
        ON CONFLICT ("Serial Number") DO UPDATE
        SET
              "Employee Markme" = excluded."Employee Markme",
              "Description" = excluded."Description",
              "Leave" = excluded."Leave";
    """
    try:
        postgres_hook = PostgresHook(postgres_conn_id="tutorial_pg_conn")
        conn = postgres_hook.get_conn()
        cur = conn.cursor()
        cur.execute(query)
        conn.commit()
        return 0
    except Exception as e:
        return 1
