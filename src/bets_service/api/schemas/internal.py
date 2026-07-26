"""Schemas de las rutas internas (servicio a servicio)."""

from pydantic import BaseModel


class UserIdsResponse(BaseModel):
    """user_ids con al menos una apuesta registrada.

    Se envuelve en un objeto en vez de devolver la lista desnuda para poder añadirle
    metadatos (paginación, corte temporal) sin romper a quien ya lo consume.
    """

    user_ids: list[str]
