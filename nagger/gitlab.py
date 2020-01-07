from gitlab import Gitlab
from functools import lru_cache


class GitLabApi(Gitlab):
    @lru_cache(maxsize=None)
    def getProject(self, project_id):
        return self.projects.get(project_id)
