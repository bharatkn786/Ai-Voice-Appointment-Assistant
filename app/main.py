from fastapi import FastAPI
from app.api.routes.call_routes import router as call_router


app = FastAPI(
    title="Appointment Voice Assistant",
)

app.include_router(call_router)


@app.get("/")
def root():
    return {
        "message": "Appointment Voice Assistant Backend is running"
    }


def main():
    print("Appointment Voice Assistant Backend")


if __name__ == "__main__":
    main()