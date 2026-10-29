DO $$ BEGIN
	CREATE ROLE cedars_runtime LOGIN PASSWORD 'runtime-local-only';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER ROLE cedars_runtime LOGIN PASSWORD 'runtime-local-only';
DO $$ BEGIN
	CREATE ROLE cedars_project_provisioner LOGIN CREATEDB PASSWORD 'provisioner-local-only';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER ROLE cedars_project_provisioner LOGIN CREATEDB PASSWORD 'provisioner-local-only';
GRANT cedars_runtime TO cedars_project_provisioner;
GRANT cedars_runtime TO cedars;
REASSIGN OWNED BY cedars TO cedars_runtime;
ALTER DATABASE cedars OWNER TO cedars_runtime;
GRANT CONNECT ON DATABASE cedars TO cedars_runtime;
GRANT CREATE ON SCHEMA public TO cedars_runtime;