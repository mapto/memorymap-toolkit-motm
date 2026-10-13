from django.db import transaction
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response


class BulkMixin:
    """Mixin adding ``bulk_upsert`` and ``bulk_update`` actions to ViewSets.

    Subclasses must define ``bulk_lookup_field`` — the model field used to
    match existing records during upsert (e.g. ``"label"`` for Concept).
    """
    bulk_lookup_field: str = ""

    @action(detail=False, methods=["post"], url_path="bulk_upsert")
    def bulk_upsert(self, request):
        """Create or update many objects in one request.

        Accepts ``{"items": [{...}, ...]}`` where each item has the fields
        accepted by the serializer. Existing records are matched by
        ``bulk_lookup_field``; matched records are updated, others are created.
        """
        items = request.data.get("items", [])
        if not items or not isinstance(items, list):
            return Response(
                {"detail": "'items' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lookup = self.bulk_lookup_field
        model = self.get_queryset().model
        serializer_cls = self.get_serializer_class()

        created, updated, errors = [], [], []
        with transaction.atomic():
            for idx, item in enumerate(items):
                try:
                    lookup_val = item.get(lookup)
                    existing = None
                    if lookup and lookup_val:
                        existing = model.objects.filter(
                            **{f"{lookup}__iexact": lookup_val}
                        ).first()
                    if existing:
                        ser = serializer_cls(existing, data=item, partial=True)
                        ser.is_valid(raise_exception=True)
                        ser.save()
                        updated.append(ser.data)
                    else:
                        ser = serializer_cls(data=item)
                        ser.is_valid(raise_exception=True)
                        ser.save()
                        created.append(ser.data)
                except Exception as exc:
                    errors.append({"index": idx, "error": str(exc)})
        return Response(
            {"created": len(created), "updated": len(updated), "errors": errors,
             "created_items": created, "updated_items": updated},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["patch"], url_path="bulk_update")
    def bulk_update(self, request):
        """Update many objects by ID.

        Accepts ``{"items": [{"id": 1, ...}, ...]}`` — each item must include
        an ``id`` field and any fields to update.
        """
        items = request.data.get("items", [])
        if not items or not isinstance(items, list):
            return Response(
                {"detail": "'items' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        model = self.get_queryset().model
        serializer_cls = self.get_serializer_class()

        updated, errors = [], []
        with transaction.atomic():
            for idx, item in enumerate(items):
                obj_id = item.pop("id", None)
                if not obj_id:
                    errors.append({"index": idx, "error": "Missing 'id'"})
                    continue
                try:
                    obj = model.objects.get(pk=obj_id)
                    ser = serializer_cls(obj, data=item, partial=True)
                    ser.is_valid(raise_exception=True)
                    ser.save()
                    updated.append(ser.data)
                except model.DoesNotExist:
                    errors.append({"index": idx, "error": f"ID {obj_id} not found"})
                except Exception as exc:
                    errors.append({"index": idx, "error": str(exc)})
        return Response(
            {"updated": len(updated), "errors": errors, "updated_items": updated},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="bulk_create")
    def bulk_create(self, request):
        """Create many objects in one request (no matching/upsert).

        Accepts ``{"items": [{...}, ...]}`` — each item is created as-is.
        Returns the created items with IDs in order.
        """
        items = request.data.get("items", [])
        if not items or not isinstance(items, list):
            return Response(
                {"detail": "'items' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer_cls = self.get_serializer_class()
        created, errors = [], []
        with transaction.atomic():
            for idx, item in enumerate(items):
                try:
                    ser = serializer_cls(data=item)
                    ser.is_valid(raise_exception=True)
                    ser.save()
                    created.append(ser.data)
                except Exception as exc:
                    errors.append({"index": idx, "error": str(exc)})
        return Response(
            {"created": len(created), "errors": errors, "items": created},
            status=status.HTTP_200_OK,
        )