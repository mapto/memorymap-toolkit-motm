from django.views.generic import DetailView, ListView

from ..models import Extraction


class ExtractionListView(ListView):
    model = Extraction
    template_name = "mmt_motm/extraction_list.html"
    context_object_name = "extractions"

    def get_queryset(self):
        return (
            Extraction.objects.select_related(
                "people_mentioned",
                "interview",
                "interview__interviewee",
            )
            .prefetch_related("concepts", "interview__urls")
            .order_by("identifier")
        )


class ExtractionDetailView(DetailView):
    model = Extraction
    template_name = "mmt_motm/extraction_detail.html"
    context_object_name = "extraction"