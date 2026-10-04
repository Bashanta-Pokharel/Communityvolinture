-- Run this file in phpMyAdmin only when the project database is damaged.
-- It deletes and recreates ONLY the Community Volunteer System demo database.

DROP DATABASE IF EXISTS community_volinturee;
CREATE DATABASE community_volinturee CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE community_volinturee;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    username VARCHAR(60) NOT NULL UNIQUE,
    email VARCHAR(190) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'volunteer',
    date_of_birth DATE NULL,
    photo_filename VARCHAR(255) NULL
);

CREATE TABLE volunteer_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    skills TEXT,
    interests TEXT,
    availability TEXT,
    location VARCHAR(120),
    photo_filename VARCHAR(255),
    education_level VARCHAR(100) NULL DEFAULT 'Intermediate (10+2) / High School',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE organization_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    organization_name VARCHAR(160),
    organization_type VARCHAR(100) NULL DEFAULT 'Non-Governmental Organization (NGO)',
    contact_person VARCHAR(120),
    contact_email VARCHAR(190) NULL,
    phone VARCHAR(40),
    location VARCHAR(120),
    description TEXT,
    logo_filename VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    required_skills TEXT,
    interests TEXT,
    availability TEXT,
    location VARCHAR(120),
    image_filename VARCHAR(255),
    organization_id INT NULL,
    start_date DATE NULL,
    end_date DATE NULL,
    min_education VARCHAR(100) NULL DEFAULT 'No Formal Education Required',
    FOREIGN KEY (organization_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    volunteer_id INT NOT NULL,
    task_id INT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'Pending',
    score DECIMAL(6,5) NOT NULL DEFAULT 0,
    review_text TEXT NULL,
    rating INT NULL DEFAULT 5,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (volunteer_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    UNIQUE (volunteer_id, task_id)
);

CREATE TABLE notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    message TEXT NOT NULL,
    is_read TINYINT NOT NULL DEFAULT 0,
    link_url VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE skill_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE interest_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE education_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    category VARCHAR(40) NOT NULL DEFAULT 'both',
    rank_level INT NOT NULL DEFAULT 1
);
