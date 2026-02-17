from fastapi import FastAPI

app = FastAPI(
    title="ProposalCreation API",
    description="ERP Proposal Creation Support System",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
