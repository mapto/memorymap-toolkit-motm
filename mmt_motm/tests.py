from django.test import TestCase
from django.utils.translation import override
from django.contrib.gis.geos import Point

from .models import Concept, Event, Extraction, Interview, LocationPoint, Person
from .serializers import ExtractionSerializer, LocationPointSerializer, TimespanSerializer
from .views import ConceptTaxonomyView, LocationTaxonomyView, SourceCategoryHeatmapView
from memorymap_toolkit.catalogs import localized_concept_label


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


class PersonDescriptionLocalizationTests(TestCase):
	def test_prosecuted_group_is_localized(self):
		person = Person.objects.create(
			given_name="Test",
			family_name="Person",
		)
		person.set_current_language("en")
		person.description = "Deutsche Jude und Jüdinnen"
		person.save()

		with override("it"):
			assert person.localized_description == "Ebrei tedeschi"

		with override("de"):
			assert person.localized_description == "Deutsche Jude und Jüdinnen"

	def test_person_metadata_values_are_localized(self):
		person = Person.objects.create(
			given_name="Test",
			family_name="Person",
			education="Realgymnasium Gießen (kein Abschluss, Zwangsabgang 1935); Hachschara (Schlesien) 1935; Jeschiwa Frankfurt 1936",
			occupation_at_emigration="Schüler",
			occupation_at_source="Bibliothekar, Universitätsbibliothek Haifa (em., 1966–1986)",
			residence_at_source="Haifa",
		)

		with override("it"):
			assert person.localized_education == (
				"Realgymnasium Gießen (nessun diploma, allontanamento forzato 1935); "
				"Hachshara (Slesia) 1935; yeshiva di Francoforte 1936"
			)
			assert person.localized_occupation_at_emigration == "studente"
			assert person.localized_occupation_at_source == (
				"Bibliotecario, Biblioteca dell'Università di Haifa (emerito, 1966–1986)"
			)
			assert person.residence_at_source == "Haifa"



class ConceptLabelLocalizationTests(TestCase):
	def test_localized_label_uses_parler_translation_table(self):
		concept = Concept.objects.create()
		for language, label in (
			("en", "Parler English"),
			("de", "Parler German"),
			("it", "Parler Italian"),
		):
			concept.set_current_language(language)
			concept.label = label
			concept.save()

		assert localized_concept_label(concept, "de") == "Parler German"
		assert localized_concept_label(concept, "it") == "Parler Italian"


class ConceptTaxonomyViewTests(TestCase):
	def test_roots_are_not_repeated_for_each_translation(self):
		concept = Concept.objects.create()
		for language, label in (
			("en", "English root"),
			("de", "Deutscher Stamm"),
			("it", "Radice italiana"),
		):
			concept.set_current_language(language)
			concept.label = label
			concept.save()

		with override("de"):
			roots = list(ConceptTaxonomyView().get_queryset())

		assert [root.pk for root in roots] == [concept.pk]

	def test_english_taxonomy_root_falls_back_for_german_view(self):
		concept = Concept.objects.create()
		concept.set_current_language("en")
		concept.label = "English-only taxonomy root"
		concept.save()

		with override("de"):
			roots = list(ConceptTaxonomyView().get_queryset())

		assert [root.pk for root in roots] == [concept.pk]
		assert roots[0].label == "English-only taxonomy root"


class LocationTaxonomyViewTests(TestCase):
	def test_locations_taxonomy_uses_go_concept_hierarchy_and_location_links(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		country = Concept.objects.create(parent=go)
		country.set_current_language("en")
		country.label = "Deutschland"
		country.save()
		city = Concept.objects.create(parent=country)
		city.set_current_language("en")
		city.label = "Berlin"
		city.save()
		location = LocationPoint.objects.create(
			current_name="Alexanderplatz",
			concept=city,
		)

		with override("de"):
			roots = list(LocationTaxonomyView().get_queryset())

		assert [root.pk for root in roots] == [country.pk]
		assert roots[0].children.get(pk=city.pk).location_point.pk == location.pk

	def test_locations_taxonomy_exposes_unassigned_points_only(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		assigned_concept = Concept.objects.create(parent=go)
		assigned_concept.set_current_language("en")
		assigned_concept.label = "Assigned place"
		assigned_concept.save()
		assigned = LocationPoint.objects.create(
			current_name="Assigned",
			concept=assigned_concept,
		)
		unassigned = LocationPoint.objects.create(current_name="Unassigned")
		view = LocationTaxonomyView()
		view.object_list = Concept.objects.none()

		with override("de"):
			context = view.get_context_data()

		assert list(context["unassigned"]) == [unassigned]
		assert assigned not in context["unassigned"]

	def test_orphan_address_is_attached_to_matching_go_city(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		country = Concept.objects.create(parent=go)
		country.set_current_language("en")
		country.label = "Deutschland"
		country.save()
		city = Concept.objects.create(parent=country)
		city.set_current_language("en")
		city.label = "Gießen"
		city.save()
		orphan = LocationPoint.objects.create(current_name="Gießen Marktplatz 15")
		view = LocationTaxonomyView()

		with override("de"):
			view.object_list = view.get_queryset()
			context = view.get_context_data()

		def find_node(nodes, label):
			for node in nodes:
				if node.label == label:
					return node
				found = find_node(node.taxonomy_children, label)
				if found:
					return found
			return None

		city_node = find_node(context["roots"], "Gießen")
		assert city_node is not None
		assert [point.pk for point in city_node.location_points] == [orphan.pk]
		assert orphan not in context["unassigned"]

	def test_reviewed_location_synonym_is_attached_to_canonical_go_node(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		region = Concept.objects.create(parent=go)
		region.set_current_language("en")
		region.label = "Palästina – Israel"
		region.save()
		point = LocationPoint.objects.create(current_name="Israel")
		view = LocationTaxonomyView()

		with override("de"):
			view.object_list = view.get_queryset()
			context = view.get_context_data()

		assert context["roots"][0].label == "Palästina – Israel"
		assert [location.pk for location in context["roots"][0].location_points] == [point.pk]
		assert point not in context["unassigned"]

	def test_koblenz_is_left_out_of_synonym_matching(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		koblenz = Concept.objects.create(parent=go)
		koblenz.set_current_language("en")
		koblenz.label = "Koblenz"
		koblenz.save()
		point = LocationPoint.objects.create(current_name="Koblenz")
		view = LocationTaxonomyView()

		with override("de"):
			view.object_list = view.get_queryset()
			context = view.get_context_data()

		assert point in context["unassigned"]


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


class GlobalSearchTests(TestCase):
	def test_search_returns_localized_categories_and_map_metadata(self):
		person = Person.objects.create(given_name="Ada", family_name="Test")
		start = LocationPoint.objects.create(current_name="Start", location=Point(8.0, 50.0))
		end = LocationPoint.objects.create(current_name="End", location=Point(9.0, 51.0))
		event = Event.objects.create(start_location=start, end_location=end)
		event.set_current_language("en")
		event.description = "Journey test"
		event.save()
		event.persons.add(person)

		response = self.client.get("/en/motm/search/?q=Ada")

		assert response.status_code == 200
		person_result = response.json()["people"][0]
		assert person_result["event_ids"] == [event.pk]
		assert person_result["location_ids"] == [start.pk, end.pk]

		response = self.client.get("/en/motm/search/?q=Journey")
		event_result = response.json()["events"][0]
		assert event_result["id"] == event.pk
		assert event_result["location_ids"] == [start.pk, end.pk]
