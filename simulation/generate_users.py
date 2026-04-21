"""
User Data Generator
===================
Generates realistic user CSV datasets for simulation tiers:
100, 200, 500, 1000, 2000, 4000, 10000 users.

Each CSV contains: name, email, password, nationality, gender,
date_of_birth, vulnerable, city_of_residence, bio, status

Run standalone:
    python -m simulation.generate_users
"""
import csv
import random
import string
from datetime import date, timedelta
from pathlib import Path

from simulation.config import USER_DATA_DIR, USER_TIERS, DEFAULT_PASSWORD

# ---------------------------------------------------------------------------
# Reference data for realistic generation
# ---------------------------------------------------------------------------

FIRST_NAMES_M = [
    "Abel", "Abraham", "Adam", "Ahmed", "Amanuel", "Bereket", "Biruk",
    "Daniel", "David", "Dawit", "Elias", "Ermias", "Eyob", "Fikru",
    "Gabriel", "Getachew", "Haile", "Ibrahim", "Isaac", "James",
    "Joseph", "Kaleb", "Kevin", "Lemuel", "Liam", "Michael", "Mohammed",
    "Nathan", "Noah", "Omar", "Paul", "Peter", "Samuel", "Solomon",
    "Tadesse", "Tewodros", "Thomas", "William", "Yohannes", "Yonas",
]

FIRST_NAMES_F = [
    "Abigail", "Amara", "Bethlehem", "Chloe", "Dina", "Eden", "Eleni",
    "Fatima", "Feven", "Grace", "Hannah", "Hana", "Helen", "Jasmine",
    "Kalkidan", "Liya", "Marta", "Mary", "Meron", "Miriam", "Nadia",
    "Nardos", "Olivia", "Rachel", "Rahel", "Ruth", "Sara", "Selam",
    "Sofia", "Tigist", "Tsion", "Yeshi", "Zara", "Zinash",
]

LAST_NAMES = [
    "Abebe", "Alemayehu", "Ali", "Amin", "Assefa", "Ayele", "Bekele",
    "Berhe", "Chala", "Dagnew", "Demeke", "Desta", "Fekadu", "Gebre",
    "Girma", "Hailu", "Hassan", "Juma", "Kabede", "Kassa", "Lemma",
    "Mekonnen", "Mengistu", "Mohammed", "Mulugeta", "Negash", "Nega",
    "Osman", "Solomon", "Tadesse", "Teferi", "Tekle", "Tesfaye",
    "Tilahun", "Wolde", "Worku", "Yilma", "Zewde",
]

NATIONALITIES = [
    "Ethiopia", "Kenya", "Nigeria", "Rwanda", "Uganda", "Tanzania",
    "Ghana", "South Africa", "Egypt", "Morocco", "Cameroon", "Senegal",
    "Ivory Coast", "DR Congo", "Zambia",
]

CITIES = [
    "Addis Ababa", "Nairobi", "Lagos", "Kigali", "Kampala", "Dar es Salaam",
    "Accra", "Johannesburg", "Cairo", "Casablanca", "Douala", "Dakar",
    "Abidjan", "Kinshasa", "Lusaka", "Cape Town", "Durban", "Maputo",
    "Harare", "Luanda",
]

GENDERS = ["Male", "Female"]
VULNERABLE_OPTIONS = ["Yes", "No", "No", "No", "No"]  # Weighted toward No

BIO_TEMPLATES = [
    "Aspiring software developer with a passion for {tech}.",
    "Data science enthusiast focused on {tech} and machine learning.",
    "Full-stack developer experienced in {tech} and cloud services.",
    "AI/ML researcher with background in {tech}.",
    "Backend engineer passionate about {tech} and scalable systems.",
    "Mobile developer with skills in {tech} and cross-platform apps.",
    "DevOps engineer specializing in {tech} and CI/CD pipelines.",
    "Cybersecurity analyst with expertise in {tech}.",
    "Product manager with technical background in {tech}.",
    "UX designer transitioning into {tech} development.",
]

TECHS = [
    "Python", "JavaScript", "TypeScript", "React", "Node.js", "FastAPI",
    "Django", "TensorFlow", "PyTorch", "AWS", "Docker", "Kubernetes",
    "Go", "Rust", "Flutter", "Swift", "PostgreSQL", "MongoDB",
]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def _random_dob() -> str:
    """Random date of birth between 1985 and 2005."""
    start = date(1985, 1, 1)
    end = date(2005, 12, 31)
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def _random_email(first: str, last: str, idx: int) -> str:
    """Generate a unique simulation email."""
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"sim.{first.lower()}.{last.lower()}.{tag}{idx}@sim.10academy.org"


def _random_bio() -> str:
    return random.choice(BIO_TEMPLATES).format(tech=random.choice(TECHS))


def generate_user(idx: int) -> dict:
    """Generate a single realistic user record."""
    gender = random.choice(GENDERS)
    first = random.choice(FIRST_NAMES_M if gender == "Male" else FIRST_NAMES_F)
    last = random.choice(LAST_NAMES)
    name = f"{first} {last}"
    email = _random_email(first, last, idx)

    return {
        "name": name,
        "email": email,
        "password": DEFAULT_PASSWORD,
        "nationality": random.choice(NATIONALITIES),
        "gender": gender,
        "date_of_birth": _random_dob(),
        "vulnerable": random.choice(VULNERABLE_OPTIONS),
        "city_of_residence": random.choice(CITIES),
        "bio": _random_bio(),
        "status": "Accepted",
    }


FIELDNAMES = [
    "name", "email", "password", "nationality", "gender",
    "date_of_birth", "vulnerable", "city_of_residence", "bio", "status",
]


def generate_tier(count: int, seed: int | None = None) -> list[dict]:
    """Generate `count` users. Uses time-based seed by default to avoid email collisions."""
    import time
    random.seed(seed if seed is not None else int(time.time() * 1000) + count)
    return [generate_user(i) for i in range(count)]


def write_csv(users: list[dict], filepath: Path):
    """Write user records to a CSV file."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(users)


def generate_all():
    """Generate CSV files for all user tiers."""
    for tier in USER_TIERS:
        users = generate_tier(tier)
        filepath = USER_DATA_DIR / f"users_{tier}.csv"
        write_csv(users, filepath)
        print(f"  Generated {filepath.name}  ({tier} users, {filepath.stat().st_size:,} bytes)")
    print(f"\nAll CSVs saved to {USER_DATA_DIR}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    generate_all()
