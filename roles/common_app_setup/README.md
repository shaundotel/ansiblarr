## Usage

```
- name: common_app_setup role
  import_role:
    name: common_app_setup
  vars:
    base_dir: "{{ application_base_dir }}"
    container_name: "{{ application_docker_name }}"
    dirs:
      - "{{ application_base_dir }}"
    docker_repo: "{{ application_docker_repo }}"
    docker_tag: "{{ application_docker_tag }}"
    dockerrun_path: "{{ application_base_dir }}/dockerrun"
    dockerupdate_path: "{{ application_base_dir }}/dockerupdate"
    gid: "{{ application_gid }}"
    group: "{{ application_group }}"
    mode: create
    files:
      - content: "{{ lookup('template', './dockerrun.j2') }}"
        dest: "{{ application_base_dir }}/dockerrun"
        owner: root
        group: root
    uid: "{{ application_uid }}"
    user: "{{ application_user }}"
```
