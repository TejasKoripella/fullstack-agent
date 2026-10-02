from security import Action, authorize, assert_not_admin

assert_not_admin()

authorize(Action("read", __file__))

try:
    authorize(Action("read", r"C:\Users\vijay koripella\Documents\work.txt"))
    raise RuntimeError("FAILED: blocked profile was accessible")
except PermissionError:
    print("PASS: work profile blocked")

try:
    authorize(Action("delete", __file__), approved=True)
    raise RuntimeError("FAILED: deletion was allowed")
except PermissionError:
    print("PASS: deletion permanently blocked")

try:
    authorize(Action("write", __file__))
    raise RuntimeError("FAILED: write happened without approval")
except PermissionError:
    print("PASS: modifications require approval")

authorize(Action("write", __file__), approved=True)
print("PASS: approved modification accepted")

print("JARVIS SECURITY LAYER ONLINE")
