from app.trade.common.repository import SQLDocuments


def po_repository(database, user_id):
    return SQLDocuments(database, user_id, "PO")
