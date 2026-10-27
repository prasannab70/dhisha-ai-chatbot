-- Disha Front Desk: MySQL schema (generated from app/db.py; the app also creates these tables on first start).
-- Run as the MySQL root user:   mysql -u root -p < sql/schema.sql

CREATE DATABASE IF NOT EXISTS disha CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'disha'@'localhost' IDENTIFIED BY 'CHANGE-THIS-PASSWORD';
GRANT ALL PRIVILEGES ON disha.* TO 'disha'@'localhost';
FLUSH PRIVILEGES;
USE disha;

CREATE TABLE IF NOT EXISTS conversations (
	id VARCHAR(40) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	channel VARCHAR(8) NOT NULL, 
	caller_name VARCHAR(120) NOT NULL, 
	muted BOOL NOT NULL, 
	updated_at DATETIME NOT NULL, 
	booking_type VARCHAR(12), 
	pending_booking TEXT, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS courses (
	id VARCHAR(32) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	track VARCHAR(60) NOT NULL, 
	fee_inr INTEGER NOT NULL, 
	duration_weeks INTEGER NOT NULL, 
	mode VARCHAR(80) NOT NULL, 
	next_batch DATE NOT NULL, 
	suited_for TEXT NOT NULL, 
	brochure_url VARCHAR(300) NOT NULL, 
	duration_text VARCHAR(40), 
	details TEXT, 
	active BOOL NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS demo_slots (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	weekday INTEGER NOT NULL, 
	start TIME NOT NULL, 
	capacity INTEGER NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS leads (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	course_id VARCHAR(32), 
	source VARCHAR(12) NOT NULL, 
	note TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS lms_sync (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	kind VARCHAR(12) NOT NULL, 
	phone VARCHAR(12) NOT NULL, 
	payload TEXT NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error VARCHAR(300) NOT NULL, 
	lms_enquiry_id INTEGER, 
	created_at DATETIME NOT NULL, 
	done_at DATETIME, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS message_log (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	channel VARCHAR(10) NOT NULL, 
	`to` VARCHAR(120) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	payload TEXT NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS staff (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(80) NOT NULL, 
	`role` VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	takes_bookings BOOL NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS appointments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	type VARCHAR(12) NOT NULL, 
	staff_id INTEGER, 
	date DATE NOT NULL, 
	time TIME NOT NULL, 
	student_name VARCHAR(120) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	course_id VARCHAR(32), 
	for_whom VARCHAR(120) NOT NULL, 
	confirm_to VARCHAR(20) NOT NULL, 
	source VARCHAR(12) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	reminder_sent BOOL NOT NULL, 
	idempotency_key VARCHAR(80), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_appt_idem UNIQUE (idempotency_key), 
	FOREIGN KEY(staff_id) REFERENCES staff (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS handoffs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id VARCHAR(40) NOT NULL, 
	staff_id INTEGER, 
	channel VARCHAR(8) NOT NULL, 
	summary TEXT NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	preferred_time VARCHAR(60) NOT NULL, 
	done BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(staff_id) REFERENCES staff (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS messages (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	conversation_id VARCHAR(40) NOT NULL, 
	`role` VARCHAR(10) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS working_hours (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	staff_id INTEGER NOT NULL, 
	weekday INTEGER NOT NULL, 
	start TIME NOT NULL, 
	end TIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(staff_id) REFERENCES staff (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
