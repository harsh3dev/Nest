"""A command to update OWASP entities from GitHub data."""

import logging
import os

import github
from django.core.management.base import BaseCommand
from github.GithubException import BadCredentialsException

from apps.github.constants import GITHUB_ITEMS_PER_PAGE
from apps.github.models import Release, Repository, sync_repository
from apps.owasp.constants import OWASP_ORGANIZATION_NAME
from apps.owasp.models import Chapter, Committee, Event, Project

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Updates OWASP entities based on their GitHub data."

    def add_arguments(self, parser):
        parser.add_argument("--offset", default=0, required=False, type=int)

    def handle(self, *_args, **options):
        try:
            gh = github.Github(os.getenv("GITHUB_TOKEN"), per_page=GITHUB_ITEMS_PER_PAGE)
            gh_owasp_organization = gh.get_organization(OWASP_ORGANIZATION_NAME)
        except BadCredentialsException:
            logger.warning(
                "Invalid GitHub token. Please create and update .env file with a valid token."
            )
            return

        remote_owasp_repositories_count = gh_owasp_organization.public_repos

        owasp_organization = None
        owasp_user = None

        chapters = []
        committees = []
        events = []
        projects = []
        releases = []

        offset = options["offset"]
        gh_repositories = gh_owasp_organization.get_repos(
            type="public",
            sort="created",
            direction="desc",
        )
        gh_repositories_count = gh_repositories.totalCount - offset
        for idx, gh_repository in enumerate(gh_repositories[offset:]):
            prefix = f"{idx + offset + 1} of {gh_repositories_count}"
            print(f"{prefix:<12} {gh_repository.name}")

            owasp_organization, repository, new_releases = sync_repository(
                gh_repository, organization=owasp_organization, user=owasp_user
            )
            releases.extend(new_releases)

            entity_key = gh_repository.name.lower()
            # OWASP chapters.
            if entity_key.startswith("www-chapter-"):
                chapters.append(Chapter.update_data(gh_repository, repository, save=False))

            # OWASP projects.
            elif entity_key.startswith("www-project-"):
                projects.append(Project.update_data(gh_repository, repository, save=False))

            # OWASP events.
            elif entity_key.startswith("www-event-"):
                events.append(Event.update_data(gh_repository, repository, save=False))

            # OWASP committees.
            elif entity_key.startswith("www-committee-"):
                committees.append(Committee.update_data(gh_repository, repository, save=False))

        # Bulk save data.
        Release.bulk_save(releases)

        Chapter.bulk_save(chapters)
        Committee.bulk_save(committees)
        Event.bulk_save(events)
        Project.bulk_save(projects)

        # Check repository counts.
        local_owasp_repositories_count = Repository.objects.filter(
            is_owasp_repository=True
        ).count()
        result = (
            "==" if remote_owasp_repositories_count == local_owasp_repositories_count else "!="
        )
        print(
            "\n"
            f"OWASP GitHub repositories count {result} synced repositories count: "
            f"{remote_owasp_repositories_count} {result} {local_owasp_repositories_count}"
        )

        gh.close()

        # Add OWASP repository to repositories list.
        for project in Project.objects.all():
            if project.owasp_repository:
                project.repositories.add(project.owasp_repository)