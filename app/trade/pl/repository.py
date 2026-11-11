from app.trade.common.repository import SQLDocuments


def pl_repository(database, user_id):
    return SQLDocuments(database, user_id, "PL")
