from src.models.models import db, User, InvTypes


class static_lookup:
    def __init__():
        pass

    def get_inv_type(self, type_id):
        """
        Get the InvType object from the database using the type_id.
        """
        inv_type = InvTypes.query.filter_by(typeID=type_id).first()
        if inv_type is None:
            return None
        return inv_type