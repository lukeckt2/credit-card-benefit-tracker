from datetime import date
as_of = date.today()
deadline = date(2026, 7, 31)
print(f"as_of: {as_of}, deadline: {deadline}, days: {(deadline - as_of).days}")
