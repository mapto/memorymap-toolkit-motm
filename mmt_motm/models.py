from django.contrib.gis.db import models
from django.template.defaultfilters import date as date_filter


class Timespan(models.Model):
    CERTAINTY_CHOICES = [
        ("certain", "Certain"),
        ("probable", "Probable"),
        ("uncertain", "Uncertain"),
        ("disputed", "Disputed"),
    ]

    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)
    certainty = models.CharField(
        max_length=20,
        choices=CERTAINTY_CHOICES,
        null=True,
        blank=True,
    )

    def __str__(self):
        fmt = "j N Y"
        if self.start and self.end and self.start != self.end:
            return f"{date_filter(self.start, fmt)} – {date_filter(self.end, fmt)}"
        if self.start:
            return date_filter(self.start, fmt)
        if self.end:
            return date_filter(self.end, fmt)
        return "—"

    CERTAINTY_ICONS = {
        "probable": ("fa-question-circle", "Probable date"),
        "uncertain": ("fa-exclamation-triangle", "Uncertain date"),
        "disputed": ("fa-balance-scale", "Disputed date"),
    }

    @property
    def certainty_icon(self):
        """Return (icon_class, tooltip) tuple or None if certain/unset."""
        return self.CERTAINTY_ICONS.get(self.certainty)


# This class contains all URLs used in the project
class URL(models.Model):
    url = models.URLField(unique=True)

    def __str__(self):
        return self.url
    
# This class contains all regions
class LocationRegion(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    polygon = models.MultiPolygonField(null=True, blank=True)

    wikidata_id = models.CharField(max_length=30, blank=True, null=True)
    geonames_id = models.CharField(max_length=20, blank=True, null=True)

    #To allow for a foreign key to another LocationRegion
    #allowing structures such as State > Region > City etc.
    part_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subregions"
    )

    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="regions"
    )

    def __str__(self):
        return self.name
    
# This class contains all Points part of Region
class LocationPoint(models.Model):
    
    current_name = models.CharField(max_length=100)

    # Alternative or historical names
    alternate_names = models.TextField(blank=True)

    postal_address = models.CharField(max_length=200, blank=True)

    description = models.TextField(blank=True)

    # Geographic coordinates (latitude/longitude point)
    location = models.PointField(null=True, blank=True)

    # External identifiers
    wikidata_id = models.CharField(max_length=30, blank=True, null=True)
    geonames_id = models.CharField(max_length=20, blank=True, null=True)

    # The region this point belongs to (e.g., city, state, country)
    region = models.ForeignKey(
        "LocationRegion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="points"
    )

    # Related URLs (references, sources, etc.)
    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="points"
    )

    def __str__(self):
        return self.current_name
    
# This class contains all the various Events from a person life that are registered
class Event(models.Model):
    
    timespan = models.ForeignKey(
        "Timespan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events"
    )

    description = models.TextField(blank=True)

    # Source URLs or references
    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="events"
    )

    # Indicates whether the event is confirmed
    is_confirmed = models.BooleanField(default=False)

    # Starting location of the event
    start_location = models.ForeignKey(
        "LocationPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_started"
    )

    # Ending location of the event
    end_location = models.ForeignKey(
        "LocationPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events_ended"
    )


    # Persons related to the event
    persons = models.ManyToManyField(
        "Person",
        blank=True,
        related_name="events"
    )

    # Concepts associated with the event
    concepts = models.ManyToManyField(
        "Concept",
        blank=True,
        related_name="events"
    )

    def __str__(self):
        if self.timespan:
            return f"Event {self.timespan}"
        return "Event"
    
# This class contains all the People linked to the Project
class Person(models.Model):
    # External archive identifiers
    identifier = models.CharField(max_length=100, unique=True, null=True, blank=True,
    db_index=True)

    given_name = models.CharField(max_length=100)
    family_name = models.CharField(max_length=100)

    previous_given_name = models.CharField(max_length=100, blank=True)
    previous_family_name = models.CharField(max_length=100, blank=True)

    lifespan = models.ForeignKey(
        "Timespan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="persons"
    )

    gender = models.CharField(max_length=50, blank=True)

    # Description or biography
    description = models.TextField(blank=True)

    # Place of birth
    birth_place = models.ForeignKey(
        "LocationPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="people_born_here"
    )

    # Place of death
    death_place = models.ForeignKey(
        "LocationPoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="people_died_here"
    )

    # Related URLs (sources, references)
    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="persons"
    )

    def __str__(self):
        return f"{self.given_name} {self.family_name}"

# This class contains all RelationshipType
class RelationshipType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    original_label = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name
        
# This class contains all Relationship among People
class Relationship(models.Model):
    
    relationship_type = models.ForeignKey(
        "RelationshipType",
        on_delete=models.CASCADE,
        related_name="relationships"
    )

    # Timespan of the relationship (if applicable)
    timespan = models.ForeignKey(
        "Timespan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relationships"
    )

    description = models.TextField(blank=True)

    # Related URLs (sources, references)
    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="relationships"
    )

    # Person who initiates or is the source of the relationship
    person_from = models.ForeignKey(
        "Person",
        on_delete=models.CASCADE,
        related_name="relationships_from"
    )

    # Person who is the target of the relationship
    person_to = models.ForeignKey(
        "Person",
        on_delete=models.CASCADE,
        related_name="relationships_to"
    )

    def __str__(self):
        return f"{self.person_from} -> {self.relationship_type} -> {self.person_to}"


class Interview(models.Model):
    # Archive identifier (external system)
    archive_id = models.CharField(max_length=100, unique=True)

    # Recording identifier (e.g., audio/video file ID)
    recording_id = models.CharField(max_length=100, blank=True)

    interview_type = models.CharField(max_length=100, blank=True)

    date = models.DateField(null=True, blank=True)

    place = models.CharField(max_length=200, blank=True)

    description = models.TextField(blank=True)

    # Related URLs (sources, references)
    urls = models.ManyToManyField(
        "URL",
        blank=True,
        related_name="interviews"
    )

    # The person conducting the interview
    interviewer = models.ForeignKey(
        "Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews_conducted"
    )

    # The person being interviewed
    interviewee = models.ForeignKey(
        "Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews_received"
    )

    def __str__(self):
        return self.archive_id
    
class Extraction(models.Model):

    
    # beleg_id - External archive identifiers
    identifier = models.CharField(max_length=100, unique=True, null=True, blank=True,
    db_index=True)

    # betrifft_personen
    people_mentioned = models.ForeignKey(
        "Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relates_to_person"
    )

    # timecode
    timecode = models.CharField(max_length=200, blank=True)


    # themen
    concepts = models.ManyToManyField(
        "Concept",
        blank=True,
        related_name="relates_to_concept"
    )

    # zitat
    quote = models.TextField(blank=True)

    # markierung
    classification = models.CharField(max_length=100, blank=True)

    event = models.ForeignKey(
        "Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relates_to_event"
    )
    event_confidence = models.CharField(max_length=200, blank=True)

    # notizien
    notes = models.TextField(blank=True)

    interview = models.ForeignKey(
        "Interview",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_from"
    )

    def __str__(self):
        return f"Extraction {self.identifier}"

class Concept(models.Model):
    label = models.CharField(max_length=200, blank=True)
    icon = models.CharField(max_length=50, blank=True, default="")
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='children'
    )

    def __str__(self):
        return f"Concept {self.label}"

    def get_root(self):
        """Walk up the parent chain to find the root category."""
        node = self
        while node.parent_id:
            node = node.parent
        return node
