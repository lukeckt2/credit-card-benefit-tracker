-- Create the database
CREATE DATABASE IF NOT EXISTS credit_card_benefits;

-- Create the runtime user (used by the application for normal operations)
CREATE USER IF NOT EXISTS 'credit_card_db_user'@'%' IDENTIFIED BY 'credit_card_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON credit_card_benefits.* TO 'credit_card_db_user'@'%';

-- Create the migration/admin user (used by Alembic and admin tasks)
CREATE USER IF NOT EXISTS 'credit_card_admin_user'@'%' IDENTIFIED BY 'credit_card_admin_password';
GRANT ALL PRIVILEGES ON credit_card_benefits.* TO 'credit_card_admin_user'@'%';

FLUSH PRIVILEGES;
