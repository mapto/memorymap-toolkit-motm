import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.translation import override
from django.contrib.gis.geos import Point
from django.urls import reverse

from .models import (
	Concept,
	Event,
	Extraction,
	Interview,
	LocationPoint,
	Person,
	Relationship,
	RelationshipType,
	Timespan,
	URL,
)
from .serializers import ExtractionSerializer, LocationPointSerializer, TimespanSerializer
from .views import ConceptTaxonomyView, LocationTaxonomyView, SourceCategoryHeatmapView
from memorymap_toolkit.catalogs import localized_concept_label
from .person_merge import PersonMergeError, merge_person_records


class SourceCategoryHeatmapViewTests(TestCase):
	def setUp(self):
		self.used_root = self.make_concept("Used concept")
		self.unused_root = self.make_concept("Unused concept")
		self.used_child = self.make_concept("Used child", parent=self.used_root)

		# The used concept is mentioned in three interviews
		for number in ("001", "002", "003"):
			interview = Interview.objects.create(archive_id=f"I-{number}")
			extraction = Extraction.objects.create(
				identifier=f"E-{number}",
				interview=interview,
			)
			extraction.concepts.add(self.used_child)

	def make_concept(self, label, parent=None):
		concept = Concept.objects.create(parent=parent)
		concept.set_current_language("en")
		concept.label = label
		concept.save()
		return concept

	def heatmap_concept_pks(self):
		view = SourceCategoryHeatmapView()
		view.object_list = Interview.objects.all()
		context = view.get_context_data()
		return [row["concept"].pk for row in context["grid"]]

	def test_heatmap_excludes_unused_root_concepts(self):
		assert self.heatmap_concept_pks() == [self.used_root.pk]

	def test_heatmap_excludes_concepts_in_fewer_than_three_interviews(self):
		rare_root = self.make_concept("Rare concept")
		rare_child = self.make_concept("Rare child", parent=rare_root)
		for number in ("001", "002"):
			extraction = Extraction.objects.create(
				identifier=f"E-rare-{number}",
				interview=Interview.objects.get(archive_id=f"I-{number}"),
			)
			extraction.concepts.add(rare_child)

		assert self.heatmap_concept_pks() == [self.used_root.pk]

	def test_heatmap_counts_interviews_not_total_mentions(self):
		busy_root = self.make_concept("Busy concept")
		busy_child = self.make_concept("Busy child", parent=busy_root)
		interview = Interview.objects.get(archive_id="I-001")
		for number in range(5):
			extraction = Extraction.objects.create(
				identifier=f"E-busy-{number}",
				interview=interview,
			)
			extraction.concepts.add(busy_child)

		assert self.heatmap_concept_pks() == [self.used_root.pk]


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


class PersonaeTaxonomyViewTests(TestCase):
	def test_personae_branch_matches_people_list_one_to_one(self):
		personae = Concept.objects.create()
		for language, label in (("en", "Personae"), ("it", "Persone")):
			personae.set_current_language(language)
			personae.label = label
			personae.save()

		legacy_code = Concept.objects.create(parent=personae)
		legacy_code.set_current_language("en")
		legacy_code.label = "Legacy collective code"
		legacy_code.save()

		family = Concept.objects.create(parent=personae)
		family.set_current_language("en")
		family.label = "Stern"
		family.save()

		person_concept = Concept.objects.create(parent=family)
		person_concept.set_current_language("en")
		person_concept.label = "Stern, Josef"
		person_concept.save()

		johanna_concept = Concept.objects.create(parent=family)
		johanna_concept.set_current_language("en")
		johanna_concept.label = "Kaminka, Johanna"
		johanna_concept.save()

		people = [
			Person.objects.create(
				identifier="PERSONAE-000",
				given_name="Johanna",
				family_name="Kaminka",
			),
			Person.objects.create(
				identifier="PERSONAE-001",
				given_name="Johanna",
				family_name="Stern",
			),
			Person.objects.create(
				identifier="PERSONAE-002",
				given_name="Ada",
				family_name="Lovelace",
			),
			Person.objects.create(
				identifier="PERSONAE-003",
				given_name="Ada",
				family_name="Lovelace",
			),
		]

		with override("it"):
			person_list_url = reverse("person_list")
			family_url = reverse("concept_detail", args=[family.pk])
			person_urls = [
				reverse("person_detail", args=[person.pk]) for person in people
			]
			concept_response = self.client.get(reverse("concept_taxonomy"))
			people_response = self.client.get(person_list_url)

		assert person_list_url == "/it/motm/persons/"
		assert concept_response.status_code == 200
		assert people_response.status_code == 200
		tree_content = concept_response.content.decode()
		assert tree_content.count('class="tree-item taxonomy-person"') == len(people) - 2
		detail_link_count = tree_content.count('class="taxonomy-person-detail-link"')
		assert detail_link_count == 0, (
			f"detail links={detail_link_count}; "
			f"Stern rendered={'Stern, Josef' in tree_content}"
		)
		assert "Legacy collective code" in tree_content
		assert "Stern" in tree_content
		assert "Stern, Josef" in tree_content
		assert "Kaminka, Johanna" in tree_content
		assert f'href="{family_url}"' in tree_content
		assert f'href="{person_list_url}"' in tree_content
		assert tree_content.count(f'href="{person_urls[0]}"') == 1
		assert tree_content.count(f'href="{person_urls[1]}"') == 0
		for person_url in person_urls[2:]:
			assert tree_content.count(f'href="{person_url}"') == 1

		list_content = people_response.content.decode()
		assert list_content.count('class="person-row"') == len(people) - 1


class PersonListLocationLinkTests(TestCase):
	def test_present_places_link_to_location_detail(self):
		birth_place = LocationPoint.objects.create(current_name="Frankfurt am Main")
		death_place = LocationPoint.objects.create(current_name="Theresienstadt")
		Person.objects.create(
			given_name="Johanna",
			family_name="Kaminka",
			birth_place=birth_place,
			death_place=death_place,
		)

		with override("en"):
			response = self.client.get(reverse("person_list"))
			birth_url = reverse("location_detail", args=[birth_place.pk])
			death_url = reverse("location_detail", args=[death_place.pk])

		assert response.status_code == 200
		content = response.content.decode()
		assert f'<a href="{birth_url}">Frankfurt am Main</a>' in content
		assert f'<a href="{death_url}">Theresienstadt</a>' in content

	def test_absent_death_place_is_not_linked(self):
		birth_place = LocationPoint.objects.create(current_name="Frankfurt am Main")
		Person.objects.create(
			given_name="Ada",
			family_name="Lovelace",
			birth_place=birth_place,
		)

		with override("en"):
			response = self.client.get(reverse("person_list"))
			birth_url = reverse("location_detail", args=[birth_place.pk])
			location_list_url = reverse("location_list")

		assert response.status_code == 200
		row = response.content.decode().split('class="person-row"', 1)[1].split("</tr>", 1)[0]
		assert row.count(f'href="{birth_url}"') == 1
		assert row.count(f'href="{location_list_url}') == 1


class PersonDetailAliasRedirectTests(TestCase):
	def test_alias_detail_url_redirects_to_the_canonical_person(self):
		canonical = Person.objects.create(
			given_name="Johanna",
			family_name="Kaminka",
		)
		alias = Person.objects.create(
			given_name="Johanna",
			family_name="Stern",
		)

		with override("it"):
			response = self.client.get(reverse("person_detail", args=[alias.pk]))
			canonical_url = reverse("person_detail", args=[canonical.pk])

		assert response.status_code == 301
		assert response["Location"] == canonical_url


class PersonAliasVisualizationTests(TestCase):
	def setUp(self):
		self.canonical = Person.objects.create(
			given_name="Johanna",
			family_name="Kaminka",
			previous_family_name="Stern",
		)
		self.alias = Person.objects.create(
			given_name="Johanna",
			family_name="Stern",
		)

	def test_person_search_returns_one_reviewed_identity(self):
		response = self.client.get(reverse("person_search"), {"q": "Johanna"})

		assert response.status_code == 200
		assert response.json() == [
			{"id": self.canonical.pk, "name": "Kaminka, Johanna"},
		]

	def test_previous_surname_search_returns_the_canonical_person(self):
		response = self.client.get(reverse("person_search"), {"q": "Stern"})

		assert response.status_code == 200
		assert response.json() == [
			{"id": self.canonical.pk, "name": "Kaminka, Johanna"},
		]

	def test_global_search_returns_one_reviewed_identity(self):
		response = self.client.get(reverse("global_search"), {"q": "Johanna"})

		assert response.status_code == 200
		assert [person["id"] for person in response.json()["people"]] == [
			self.canonical.pk,
		]

	def test_event_detail_renders_an_alias_identity_once(self):
		event = Event.objects.create()
		event.persons.add(self.canonical, self.alias)

		response = self.client.get(reverse("event_detail", args=[event.pk]))

		assert response.status_code == 200
		content = response.content.decode()
		canonical_url = reverse("person_detail", args=[self.canonical.pk])
		alias_url = reverse("person_detail", args=[self.alias.pk])
		assert content.count(f'href="{canonical_url}"') == 1
		assert f'href="{alias_url}"' not in content

	def test_location_detail_deduplicates_people_and_event_participants(self):
		location = LocationPoint.objects.create(current_name="Alias test location")
		self.canonical.birth_place = location
		self.canonical.save()
		self.alias.birth_place = location
		self.alias.save()
		event = Event.objects.create(start_location=location)
		event.persons.add(self.canonical, self.alias)

		response = self.client.get(reverse("location_detail", args=[location.pk]))

		assert response.status_code == 200
		content = response.content.decode()
		canonical_url = reverse("person_detail", args=[self.canonical.pk])
		alias_url = reverse("person_detail", args=[self.alias.pk])
		assert content.count(f'href="{canonical_url}"') == 2
		assert f'href="{alias_url}"' not in content

	def test_concept_detail_people_collection_deduplicates_aliases(self):
		concept = Concept.objects.create()
		concept.set_current_language("en")
		concept.label = "Alias mention concept"
		concept.save()
		for person, identifier in (
			(self.canonical, "ALIAS-MENTION-CANONICAL"),
			(self.alias, "ALIAS-MENTION-VARIANT"),
		):
			extraction = Extraction.objects.create(
				identifier=identifier,
				people_mentioned=person,
			)
			extraction.concepts.add(concept)

		response = self.client.get(reverse("concept_detail", args=[concept.pk]))

		assert response.status_code == 200
		assert [person.pk for person in response.context["persons"]] == [
			self.canonical.pk,
		]

	def test_personae_taxonomy_and_concept_detail_open_canonical_person(self):
		personae = Concept.objects.create()
		for language, label in (("en", "Personae"), ("it", "Persone")):
			personae.set_current_language(language)
			personae.label = label
			personae.save()
		family = Concept.objects.create(parent=personae)
		family.set_current_language("en")
		family.label = "Stern"
		family.save()
		person_concept = Concept.objects.create(parent=family)
		person_concept.set_current_language("en")
		person_concept.label = "Kaminka, Johanna"
		person_concept.save()
		other_root = Concept.objects.create()
		other_root.set_current_language("en")
		other_root.label = "Kultureme"
		other_root.save()
		other_concept = Concept.objects.create(parent=other_root)
		other_concept.set_current_language("en")
		other_concept.label = "Kaminka, Johanna"
		other_concept.save()

		with override("it"):
			taxonomy_response = self.client.get(reverse("concept_taxonomy"))
			person_concept_response = self.client.get(
				reverse("concept_detail", args=[person_concept.pk])
			)
			other_concept_response = self.client.get(
				reverse("concept_detail", args=[other_concept.pk])
			)
			person_url = reverse("person_detail", args=[self.canonical.pk])

		assert taxonomy_response.status_code == 200
		tree_content = taxonomy_response.content.decode()
		assert tree_content.count(f'href="{person_url}"') == 1
		assert f'href="{reverse("concept_detail", args=[person_concept.pk])}"' not in tree_content
		assert person_concept_response.status_code == 302
		assert person_concept_response["Location"] == person_url
		assert other_concept_response.status_code == 200


class PersonMergeTests(TestCase):
	def test_api_merge_action_returns_merged_ids(self):
		canonical = Person.objects.create(
			given_name="Johanna",
			family_name="Kaminka",
		)
		duplicate = Person.objects.create(
			given_name="Johanna",
			family_name="Stern",
		)
		user = get_user_model().objects.create_user(username="person-merger")
		self.client.force_login(user)

		response = self.client.post(
			reverse("api-person-merge", args=[canonical.pk]),
			data=json.dumps({"duplicate_ids": [duplicate.pk]}),
			content_type="application/json",
		)

		assert response.status_code == 200, response.content.decode()
		assert response.json() == {
			"canonical_id": canonical.pk,
			"merged_ids": [duplicate.pk],
		}
		assert not Person.objects.filter(pk=duplicate.pk).exists()

	def test_merge_preserves_all_person_relationships(self):
		canonical = Person.objects.create(
			identifier="MERGE-CANONICAL",
			given_name="Johanna",
			family_name="Kaminka",
		)
		duplicate = Person.objects.create(
			given_name="Johanna",
			family_name="Stern",
		)
		relative = Person.objects.create(
			given_name="Josef",
			family_name="Stern",
		)
		lifespan = Timespan.objects.create()
		birth_place = LocationPoint.objects.create(current_name="Birthplace")
		death_place = LocationPoint.objects.create(current_name="Deathplace")
		duplicate.gender = "female"
		duplicate.education = "Secondary school"
		duplicate.occupation_at_source = "Teacher"
		duplicate.lifespan = lifespan
		duplicate.birth_place = birth_place
		duplicate.death_place = death_place
		duplicate.save()
		duplicate.set_current_language("en")
		duplicate.description = "Merged biography"
		duplicate.save()
		url = URL.objects.create(url="https://example.test/person-merge")
		canonical.urls.add(url)
		duplicate.urls.add(url)

		event = Event.objects.create()
		event.persons.add(canonical, duplicate)
		interview = Interview.objects.create(
			archive_id="MERGE-INTERVIEW",
			interviewee=duplicate,
			interviewer=duplicate,
		)
		extraction = Extraction.objects.create(
			identifier="MERGE-EXTRACTION",
			people_mentioned=duplicate,
		)
		relationship_type = RelationshipType.objects.create()
		relationship_type.set_current_language("en")
		relationship_type.name = "aunt"
		relationship_type.save()
		relationship = Relationship.objects.create(
			relationship_type=relationship_type,
			person_from=duplicate,
			person_to=relative,
		)
		self_relationship = Relationship.objects.create(
			relationship_type=relationship_type,
			person_from=duplicate,
			person_to=canonical,
		)

		merged_person, merged_ids = merge_person_records(
			canonical.pk,
			[duplicate.pk],
		)

		assert merged_person.pk == canonical.pk
		assert merged_ids == [duplicate.pk]
		assert not Person.objects.filter(pk=duplicate.pk).exists()
		assert merged_person.previous_family_name == "Stern"
		assert merged_person.gender == "female"
		assert merged_person.education == "Secondary school"
		assert merged_person.occupation_at_source == "Teacher"
		assert merged_person.lifespan_id == lifespan.pk
		assert merged_person.birth_place_id == birth_place.pk
		assert merged_person.death_place_id == death_place.pk
		merged_person.set_current_language("en")
		assert merged_person.description == "Merged biography"
		assert list(event.persons.values_list("pk", flat=True)) == [canonical.pk]
		assert (
			Extraction.objects.get(pk=extraction.pk).people_mentioned_id
			== canonical.pk
		)
		interview.refresh_from_db()
		assert interview.interviewee_id == canonical.pk
		assert interview.interviewer_id == canonical.pk
		relationship.refresh_from_db()
		assert relationship.person_from_id == canonical.pk
		assert relationship.person_to_id == relative.pk
		assert not Relationship.objects.filter(pk=self_relationship.pk).exists()
		assert list(merged_person.urls.values_list("pk", flat=True)) == [url.pk]

	def test_merge_rejects_conflicting_external_identifiers(self):
		canonical = Person.objects.create(
			identifier="MERGE-IDENTIFIER-A",
			given_name="Johanna",
			family_name="Kaminka",
		)
		duplicate = Person.objects.create(
			identifier="MERGE-IDENTIFIER-B",
			given_name="Johanna",
			family_name="Stern",
		)

		with self.assertRaises(PersonMergeError):
			merge_person_records(canonical.pk, [duplicate.pk])

		assert Person.objects.filter(pk=canonical.pk).exists()
		assert Person.objects.filter(pk=duplicate.pk).exists()
		assert Person.objects.get(pk=canonical.pk).previous_family_name == ""


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
		city_node = roots[0].taxonomy_children[0]
		assert city_node.pk == city.pk
		assert city_node.location_points == [location]
		assert city_node.location_link is None

	def test_concept_and_locations_taxonomies_share_go_tree(self):
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
			current_name="Berlin",
			concept=city,
		)

		with override("de"):
			concept_roots = list(ConceptTaxonomyView().get_queryset())
			location_roots = list(LocationTaxonomyView().get_queryset())

		concept_go = next(root for root in concept_roots if root.pk == go.pk)
		concept_country = concept_go.taxonomy_children[0]
		concept_city = concept_country.taxonomy_children[0]
		location_city = location_roots[0].taxonomy_children[0]
		assert location_roots[0].pk == concept_country.pk
		assert location_city.pk == concept_city.pk
		assert location_city.location_points == concept_city.location_points == [location]
		assert location_city.location_link == concept_city.location_link == location

		concept_response = self.client.get(reverse("concept_taxonomy"))
		location_response = self.client.get(reverse("location_taxonomy"))
		assert concept_response.status_code == 200
		assert location_response.status_code == 200
		assert b"<details class=\"taxonomy-branch\">" in concept_response.content
		assert b"<details class=\"taxonomy-branch\">" in location_response.content
		country_url = reverse("concept_detail", args=[country.pk])
		assert f'href="{country_url}"'.encode() in concept_response.content
		assert b"Deutschland" in concept_response.content
		assert b"taxonomy-node-actions" not in concept_response.content
		assert b"taxonomy-node-actions" not in location_response.content
		assert b"Open concept" not in concept_response.content
		assert b"Open location" not in location_response.content

	def test_location_concept_url_redirects_to_location_detail(self):
		concept = Concept.objects.create()
		concept.set_current_language("en")
		concept.label = "Berlin"
		concept.save()
		location = LocationPoint.objects.create(
			current_name="Berlin",
			concept=concept,
		)

		response = self.client.get(reverse("concept_detail", args=[concept.pk]))

		assert response.status_code == 302
		assert response.url == reverse("location_detail", args=[location.pk])

	def test_unassigned_go_location_concept_url_redirects_to_location_detail(self):
		go = Concept.objects.create()
		go.set_current_language("en")
		go.label = "GO – geographischer Ort"
		go.save()
		city = Concept.objects.create(parent=go)
		city.set_current_language("en")
		city.label = "Berlin"
		city.save()
		location = LocationPoint.objects.create(current_name="Berlin")

		response = self.client.get(reverse("concept_detail", args=[city.pk]))

		assert response.status_code == 302
		assert response.url == reverse("location_detail", args=[location.pk])

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


class LocationDetailViewTests(TestCase):
	def test_events_table_lists_person_between_date_and_place(self):
		location = LocationPoint.objects.create(current_name="Event location")
		person = Person.objects.create(given_name="Ada", family_name="Lovelace")
		event = Event.objects.create(start_location=location)
		event.persons.add(person)

		with override("en"):
			response = self.client.get(
				reverse("location_detail", args=[location.pk])
			)
			person_url = reverse("person_detail", args=[person.pk])

		assert response.status_code == 200
		content = response.content.decode()
		assert content.index("<th>Date</th>") < content.index("<th>Person</th>")
		assert content.index("<th>Person</th>") < content.index("<th>Place</th>")
		assert f'href="{person_url}">Ada Lovelace</a>' in content


class EventListViewTests(TestCase):
	def test_timeline_lists_person_between_date_and_place(self):
		location = LocationPoint.objects.create(current_name="Timeline location")
		person = Person.objects.create(given_name="Ada", family_name="Lovelace")
		event = Event.objects.create(start_location=location)
		event.persons.add(person)

		with override("en"):
			response = self.client.get(reverse("event_list"))
			person_url = reverse("person_detail", args=[person.pk])

		assert response.status_code == 200
		content = response.content.decode()
		assert content.index('data-col="0">Date') < content.index('data-col="1">Person')
		assert content.index('data-col="1">Person') < content.index('data-col="2">Place')
		assert f'href="{person_url}">Ada Lovelace</a>' in content

	def test_timeline_orders_events_by_start_then_end_date(self):
		long_1950s = Event.objects.create(
			timespan=Timespan.objects.create(start=date(1950, 1, 1), end=date(1960, 1, 1))
		)
		short_1950s = Event.objects.create(
			timespan=Timespan.objects.create(start=date(1950, 1, 1), end=date(1955, 1, 1))
		)
		early = Event.objects.create(
			timespan=Timespan.objects.create(start=date(1940, 1, 1), end=date(1945, 1, 1))
		)

		with override("en"):
			response = self.client.get(reverse("event_list"))

		assert response.status_code == 200
		assert [event.pk for event in response.context["events"]] == [
			early.pk,
			short_1950s.pk,
			long_1950s.pk,
		]


class ConceptListViewTests(TestCase):
	def make_concept(self, label):
		concept = Concept.objects.create()
		concept.set_current_language("en")
		concept.label = label
		concept.save()
		return concept

	def test_word_cloud_shows_only_concepts_with_at_least_two_quotes(self):
		self.make_concept("Unused concept")
		single = self.make_concept("Single quote concept")
		repeated = self.make_concept("Repeated quote concept")
		Extraction.objects.create(identifier="E-single-001").concepts.add(single)
		for number in ("001", "002"):
			Extraction.objects.create(identifier=f"E-repeated-{number}").concepts.add(repeated)

		with override("en"):
			response = self.client.get(reverse("concept_list"))

		assert response.status_code == 200
		assert [concept.pk for concept in response.context["concepts"]] == [repeated.pk]


class LocationListViewTests(TestCase):
	def test_word_cloud_shows_only_places_with_at_least_two_events(self):
		LocationPoint.objects.create(current_name="Unused place")
		single = LocationPoint.objects.create(current_name="Single event place")
		repeated = LocationPoint.objects.create(current_name="Repeated event place")
		Event.objects.create(start_location=single)
		Event.objects.create(start_location=repeated)
		Event.objects.create(end_location=repeated)

		with override("en"):
			response = self.client.get(reverse("location_list"))

		assert response.status_code == 200
		assert [location.pk for location in response.context["locations"]] == [repeated.pk]


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
