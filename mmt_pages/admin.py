from django.contrib import admin
from parler.admin import TranslatableAdmin, TranslatableStackedInline

from .models import Page, Section

class SectionInline(TranslatableStackedInline):
	model = Section
	fields = ['title', 'order', 'body']
	extra = 1

class PageAdmin(TranslatableAdmin):
	inlines = [SectionInline]

	class Meta:
		model = Page
		fields = ['title', 'order', 'body']

admin.site.register(Page, PageAdmin)
