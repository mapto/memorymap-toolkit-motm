from django.test import TestCase
from django.utils.translation import override

from .models import Concept, Extraction, Interview, LocationPoint
from .serializers import ExtractionSerializer, LocationPointSerializer, TimespanSerializer
from .views import SourceCategoryHeatmapView


class SourceCategoryHeatmapViewTests(TestCase):
	def setUp(self):
		self.used_root = Concept.objects.create()
		self.used_root.set_current_language("en")
		self.used_root.label = "Used category"
		self.used_root.save()

		self.unused_root = Concept.objects.create()
		self.unused_root.set_current_language("en")
		self.unused_root.label = "Unused category"
		self.unused_root.save()

		used_child = Concept.objects.create(parent=self.used_root)
		used_child.set_current_language("en")
		used_child.label = "Used child"
		used_child.save()

		interview = Interview.objects.create(archive_id="I-001")
		extraction = Extraction.objects.create(
			identifier="E-001",
			interview=interview,
		)
		extraction.concepts.add(used_child)

	def test_heatmap_excludes_unused_root_categories(self):
		view = SourceCategoryHeatmapView()
		view.object_list = Interview.objects.all()
		context = view.get_context_data()

		assert [row["category"].pk for row in context["grid"]] == [
			self.used_root.pk
		]


class ExtractionSerializerTests(TestCase):
	def test_blank_notes_are_valid(self):
		serializer = ExtractionSerializer(
			data={"identifier": "E-blank-notes", "notes": ""}
		)

		assert serializer.is_valid(), serializer.errors



class TimespanSerializerTests(TestCase):
	def test_unknown_certainty_is_valid(self):
		serializer = TimespanSerializer(data={"certainty": "unknown"})

		assert serializer.is_valid(), serializer.errors


class ExtractionLanguageLabelTests(TestCase):
	def test_language_label_is_localized(self):
		extraction = Extraction(language="de")

		with override("de"):
			assert extraction.language_label == "Deutsch"

		with override("it"):
			assert extraction.language_label == "Tedesco"

	def test_language_label_preserves_empty_and_unknown_codes(self):
		assert Extraction(language="").language_label == ""
		assert Extraction(language="xx").language_label == "xx"


class LocationPointSerializerTests(TestCase):
	def test_update_coordinates_writes_point_field(self):
		location = LocationPoint.objects.create(current_name="Test location")
		serializer = LocationPointSerializer(
			location,
			data={"latitude": 50.59, "longitude": 8.67},
			partial=True,
		)

		assert serializer.is_valid(), serializer.errors
		serializer.save()
		location.refresh_from_db()

		assert location.location.y == 50.59
		assert location.location.x == 8.67
